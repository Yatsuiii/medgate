"""The review step on the live server: cited orders still grade correct, runs write nothing, approved orders round-trip.

Every test that writes deletes what it wrote, and the resource counts are checked against their starting values.
"""

import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest

from medgate.fhir import FhirClient
from medgate.gates import FORMAT_ONLY, FULL, GateConfig
from medgate.grade import GRADER, grade
from medgate.llm import ScriptedLlm, ToolCall, Turn
from medgate.loop import TaskResult
from medgate.protocol import FHIR_BASE
from medgate.review import commit, proposals
from medgate.tasks import load_functions, load_tasks
from medgate.tool_agent import run_tool_task

pytestmark = pytest.mark.live
FHIR = FhirClient()
if not FHIR.is_up() or not GRADER.exists():
    pytest.skip("needs the FHIR server and vendor/refsol.py", allow_module_level=True)

TASKS = load_tasks()
FUNCS = load_functions()
NOW = "2023-11-13T10:15:00+00:00"
NOW_TIME = datetime.fromisoformat(NOW)
WRITABLE = ("MedicationRequest", "ServiceRequest", "Observation")
BOTH_ARMS = pytest.mark.parametrize("cfg", [FORMAT_ONLY, FULL], ids=["T", "TG"])


def counts() -> dict[str, int]:
    """Live resource counts. no-cache matters: the server reuses identical searches, so a count right after a write
    would otherwise still show the old number."""
    fresh = {"Cache-Control": "no-cache"}
    url = "{}{}?_summary=count&_format=json"
    return {rt: int(httpx.get(url.format(FHIR_BASE, rt), headers=fresh).json()["total"]) for rt in WRITABLE}


@pytest.fixture
def unchanged_server() -> Iterator[list[str]]:
    """Yields a list to put created references in; deletes them afterwards and checks the counts are back."""
    before, created = counts(), []
    yield created
    for reference in created:
        httpx.delete(f"{FHIR_BASE}{reference}").raise_for_status()
    assert counts() == before


def newest(mrn: str, code: str, since: datetime | None = None) -> dict[str, Any] | None:
    url = f"{FHIR_BASE}Observation?patient={mrn}&code={code}&_count=5000&_format=json"
    found = [e["resource"] for e in json.loads(str(FHIR.get(url).data)).get("entry", [])]
    found = [r for r in found if since is None or datetime.fromisoformat(r["effectiveDateTime"]) >= since]
    return max(found, key=lambda r: datetime.fromisoformat(r["effectiveDateTime"]), default=None)


def step(name: str, arguments: dict[str, Any]) -> Turn:
    return Turn(calls=(ToolCall(f"call_{name}", name, json.dumps(arguments)),))


def cite(observation: dict[str, Any]) -> list[dict[str, str]]:
    return [{"reference": f"Observation/{observation['id']}"}]


def base_order(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "authoredOn": NOW,
        "status": "active",
        "intent": "order",
        "subject": {"reference": f"Patient/{case['eval_MRN']}"},
    }


def first_case(category: str, code: str, wanted: Any, since: datetime | None = None) -> tuple[dict[str, Any], Any]:
    for case in TASKS:
        if case["id"].startswith(f"{category}_") and wanted(reading := newest(case["eval_MRN"], code, since)):
            return case, reading
    pytest.fail(f"no {category} case matches")


def potassium_case() -> tuple[dict[str, Any], list[Turn]]:
    case, k = first_case("task9", "K", lambda r: r is not None and r["valueQuantity"]["value"] < 3.5)
    value = k["valueQuantity"]["value"]
    medication = {
        **base_order(case),
        "medicationCodeableConcept": {"coding": [{"system": "http://hl7.org/fhir/sid/ndc", "code": "40032-917-01"}]},
        "dosageInstruction": [
            {"route": "oral", "doseAndRate": [{"doseQuantity": {"value": (3.5 - value) / 0.1 * 10, "unit": "mEq"}}]}
        ],
        "reasonReference": cite(k),
    }
    level = {
        **base_order(case),
        "priority": "stat",
        "code": {"coding": [{"system": "http://loinc.org", "code": "2823-3"}]},
        "occurrenceDateTime": "2023-11-14T08:00:00+00:00",
        "reasonReference": cite(k),
    }
    search = step("observation_search_labs", {"patient": case["eval_MRN"], "code": "K"})
    turns = [search, step("medicationrequest_create", medication), step("servicerequest_create", level)]
    return case, [*turns, step("finish", {"answer": [value]})]


def magnesium_case() -> tuple[dict[str, Any], list[Turn]]:
    since = NOW_TIME - timedelta(hours=24)
    case, mg = first_case("task5", "MG", lambda r: r is not None and r["valueQuantity"]["value"] <= 1.9, since)
    value = mg["valueQuantity"]["value"]
    grams = 1 if value >= 1.5 else 2 if value >= 1 else 4
    dose = {"doseQuantity": {"value": grams, "unit": "g"}, "rateQuantity": {"value": grams, "unit": "h"}}
    medication = {
        **base_order(case),
        "medicationCodeableConcept": {"coding": [{"system": "http://hl7.org/fhir/sid/ndc", "code": "0338-1715-40"}]},
        "dosageInstruction": [{"route": "IV", "doseAndRate": [dose]}],
        "reasonReference": cite(mg),
    }
    search = step("observation_search_labs", {"patient": case["eval_MRN"], "code": "MG"})
    return case, [search, step("medicationrequest_create", medication), step("finish", {"answer": [value]})]


def a1c_case() -> tuple[dict[str, Any], list[Turn]]:
    year_ago = NOW_TIME - timedelta(days=365)
    old = lambda r: r is not None and datetime.fromisoformat(r["effectiveDateTime"]) < year_ago  # noqa: E731
    case, a1c = first_case("task10", "A1C", old)
    order = {
        **base_order(case),
        "priority": "stat",
        "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4"}]},
    }
    answer = [a1c["valueQuantity"]["value"], a1c["effectiveDateTime"]]
    search = step("observation_search_labs", {"patient": case["eval_MRN"], "code": "A1C"})
    return case, [
        search,
        step("servicerequest_create", {**order, "reasonReference": cite(a1c)}),
        step("finish", {"answer": answer}),
    ]


def play(case: dict[str, Any], turns: list[Turn], cfg: GateConfig) -> TaskResult:
    return run_tool_task(case, FUNCS, ScriptedLlm(turns), FHIR, cfg)


@BOTH_ARMS
@pytest.mark.parametrize("scenario", [potassium_case, magnesium_case, a1c_case], ids=["task9", "task5", "task10"])
def test_orders_that_cite_their_evidence_still_grade_correct(cfg: GateConfig, scenario: Any) -> None:
    case, turns = scenario()
    result = play(case, turns, cfg)
    assert result.rejected_posts == 0 and grade(case, result) is True


def test_tg_rejects_an_order_citing_a_record_the_agent_never_read() -> None:
    case, turns = potassium_case()
    forged = json.loads(turns[1].calls[0].arguments)
    forged["reasonReference"] = [{"reference": "Observation/999999999"}]
    rejected = play(case, [turns[0], step("medicationrequest_create", forged), turns[-1]], FULL)
    accepted = play(case, [turns[0], step("medicationrequest_create", forged), turns[-1]], FORMAT_ONLY)
    assert rejected.rejected_posts == 1 and "999999999" in rejected.history[3]["content"]
    assert accepted.rejected_posts == 0


def test_a_run_writes_nothing_to_the_server(unchanged_server: list[str]) -> None:
    case, turns = potassium_case()
    assert len(proposals(play(case, turns, FULL).history, FHIR)) == 2


def test_an_approved_order_is_written_as_fhir_and_reads_back_whole(unchanged_server: list[str]) -> None:
    case, turns = potassium_case()
    medication, _ = proposals(play(case, turns, FULL).history, FHIR)
    assert medication.findings is None and json.loads(medication.evidence[0])["valueQuantity"]["value"] < 3.5
    committed = commit(medication, FHIR)
    unchanged_server.append(committed.reference)
    stored = FHIR.read(committed.reference)
    assert committed.dropped == () and stored["dosageInstruction"][0]["route"] == {"text": "oral"}
    assert stored["reasonReference"] == medication.payload["reasonReference"]


def test_the_server_silently_drops_a_route_written_in_the_benchmark_shape(unchanged_server: list[str]) -> None:
    """Why commit converts to FHIR first: written as the grader wants it, the route is lost without an error."""
    case, turns = potassium_case()
    medication, _ = proposals(play(case, turns, FULL).history, FHIR)
    reference = FHIR.create("MedicationRequest", medication.payload)
    unchanged_server.append(reference)
    assert "route" not in FHIR.read(reference)["dosageInstruction"][0]
