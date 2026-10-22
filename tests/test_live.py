"""Live tests against the local MedAgentBench FHIR server (work/fhir-server/run_fhir.sh, port 8080)."""

import json
from typing import Any

import httpx
import pytest

from medgate.fhir import FhirClient
from medgate.gates import FULL, REFERENCE, WITH_VALIDATION
from medgate.llm import ScriptedLlm
from medgate.loop import Status, run_task
from medgate.protocol import FHIR_BASE, POST_ACCEPTED
from medgate.tasks import load_functions, load_tasks

pytestmark = pytest.mark.live
FHIR = FhirClient()
if not FHIR.is_up():
    pytest.skip("FHIR server is not running on localhost:8080", allow_module_level=True)

TASKS = load_tasks()
FUNCS = load_functions()
CATEGORIES = sorted({t["id"].split("_")[0] for t in TASKS}, key=lambda c: int(c[4:]))
MRN = "S6534835"
SERVICE_REQUEST = {
    "resourceType": "ServiceRequest",
    "code": {"coding": [{"system": "http://loinc.org", "code": "5792-7"}]},
    "authoredOn": "2023-11-13T10:15:00+00:00",
    "status": "active",
    "intent": "order",
    "priority": "stat",
    "subject": {"reference": f"Patient/{MRN}"},
}


def first_task(category: str) -> dict[str, Any]:
    return next(t for t in TASKS if t["id"].startswith(f"{category}_"))


def post(resource: str, payload: dict[str, Any]) -> str:
    return f"POST {FHIR_BASE}{resource}\n{json.dumps(payload)}"


def test_benchmark_has_300_tasks_in_10_categories_of_30() -> None:
    assert len(TASKS) == 300 and len(CATEGORIES) == 10
    assert all(sum(t["id"].startswith(f"{c}_") for t in TASKS) == 30 for c in CATEGORIES)


def test_functions_cover_six_reads_and_three_writes() -> None:
    names = [f["name"] for f in FUNCS]
    assert sum(n.startswith("GET") for n in names) == 6 and sum(n.startswith("POST") for n in names) == 3


@pytest.mark.parametrize("category", CATEGORIES)
def test_every_category_patient_exists_in_the_live_database(category: str) -> None:
    mrn = first_task(category)["eval_MRN"]
    fetched = FHIR.get(f"{FHIR_BASE}Patient?identifier={mrn}&_format=json")
    assert fetched.error is None and mrn in str(fetched.data)


def test_get_returns_text_because_of_the_reference_content_type_quirk() -> None:
    fetched = FHIR.get(f"{FHIR_BASE}Patient?name=Peter&birthdate=1932-12-29&_format=json")
    assert isinstance(fetched.data, str) and MRN in fetched.data


def test_get_error_for_a_bad_url() -> None:
    assert FHIR.get(f"{FHIR_BASE}NoSuchResource?_format=json").error is not None


def test_scripted_agent_solves_task_1_1_end_to_end() -> None:
    case = first_task("task1")
    llm = ScriptedLlm([f"GET {FHIR_BASE}Patient?name=Peter&birthdate=1932-12-29", f'FINISH(["{MRN}"])'])
    result = run_task(case, FUNCS, llm, FHIR, REFERENCE)
    assert result.status is Status.COMPLETED and json.loads(result.result or "") == case["sol"]
    assert MRN in result.history[2]["content"]


def test_strict_fhir_validation_rejects_payloads_the_grader_requires() -> None:
    """Why gate 1 uses the benchmark spec, not the server's $validate: the grader's own answers are not valid FHIR."""
    task8 = {**SERVICE_REQUEST, "note": {"text": "Situation: knee injury"}}
    task5 = {
        "resourceType": "MedicationRequest",
        "medicationCodeableConcept": {"coding": [{"system": "http://hl7.org/fhir/sid/ndc", "code": "0338-1715-40"}]},
        "authoredOn": "2023-11-13T10:15:00+00:00",
        "dosageInstruction": [{"route": "IV", "doseAndRate": [{"doseQuantity": {"value": 2, "unit": "g"}}]}],
        "status": "active",
        "intent": "order",
        "subject": {"reference": f"Patient/{MRN}"},
    }
    for resource, payload in (("ServiceRequest", task8), ("MedicationRequest", task5)):
        outcome = httpx.post(
            f"{FHIR_BASE}{resource}/$validate",
            json=payload,
            headers={"Content-Type": "application/fhir+json"},
            timeout=60,
        ).json()
        assert any(i["severity"] in ("error", "fatal") for i in outcome["issue"]), resource


def test_gated_loop_blocks_a_payload_missing_required_fields_then_accepts_the_fix() -> None:
    incomplete = {"resourceType": "ServiceRequest", "subject": {"reference": f"Patient/{MRN}"}}
    case = {**first_task("task10"), "instruction": f"Order an A1C test for {MRN}"}
    llm = ScriptedLlm([post("ServiceRequest", incomplete), post("ServiceRequest", SERVICE_REQUEST), "FINISH([])"])
    result = run_task(case, FUNCS, llm, FHIR, WITH_VALIDATION)
    assert result.rejected_posts == 1 and "required field" in result.history[2]["content"]
    assert result.history[4]["content"] == POST_ACCEPTED


def test_reference_loop_accepts_the_same_incomplete_write() -> None:
    incomplete = {"resourceType": "ServiceRequest", "subject": {"reference": f"Patient/{MRN}"}}
    llm = ScriptedLlm([post("ServiceRequest", incomplete), "FINISH([])"])
    result = run_task(first_task("task10"), FUNCS, llm, FHIR, REFERENCE)
    assert result.history[2]["content"] == POST_ACCEPTED and result.rejected_posts == 0


def test_evidence_gate_blocks_a_write_for_a_patient_nobody_looked_up() -> None:
    nobody = {**SERVICE_REQUEST, "subject": {"reference": "Patient/S0000000"}}
    case = {**first_task("task10"), "instruction": "Order an A1C test for the patient named Nobody"}
    llm = ScriptedLlm([post("ServiceRequest", nobody), 'FINISH(["Patient not found"])'])
    result = run_task(case, FUNCS, llm, FHIR, FULL)
    assert result.rejected_posts == 1 and "S0000000" in result.history[2]["content"]
    assert result.status is Status.COMPLETED


def test_evidence_gate_allows_a_write_after_the_patient_was_retrieved() -> None:
    case = {**first_task("task10"), "instruction": "Order an A1C test for Peter Stafford born 1932-12-29"}
    llm = ScriptedLlm(
        [
            f"GET {FHIR_BASE}Patient?name=Peter&birthdate=1932-12-29",
            post("ServiceRequest", SERVICE_REQUEST),
            "FINISH([])",
        ]
    )
    result = run_task(case, FUNCS, llm, FHIR, FULL)
    assert result.rejected_posts == 0 and result.history[4]["content"] == POST_ACCEPTED
