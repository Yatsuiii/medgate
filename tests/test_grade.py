"""The grading adapter against the real benchmark grader, using scripted oracle agents on the live server."""

import json
from datetime import datetime
from typing import Any

import pytest

from medgate.fhir import FhirClient
from medgate.gates import FULL, REFERENCE, WITH_VALIDATION, GateConfig
from medgate.grade import GRADER, grade
from medgate.llm import ScriptedLlm
from medgate.loop import Status, TaskResult, run_task
from medgate.protocol import FHIR_BASE
from medgate.tasks import load_functions, load_tasks

pytestmark = pytest.mark.live
FHIR = FhirClient()
if not FHIR.is_up() or not GRADER.exists():
    pytest.skip("needs the FHIR server and vendor/refsol.py", allow_module_level=True)

TASKS = {t["id"]: t for t in load_tasks()}
FUNCS = load_functions()
NOW = "2023-11-13T10:15:00+00:00"
ORTHO_NOTE = (
    "Situation: acute left knee injury, Background: radiology report indicates ACL tear. Assessment: ACL tear "
    "grade II. Recommendation: request for Orthopedic service to evaluate and provide management recommendations."
)


def play(task_id: str, replies: list[str], cfg: GateConfig = REFERENCE) -> TaskResult:
    return run_task(TASKS[task_id], FUNCS, ScriptedLlm(replies), FHIR, cfg)


def post(resource: str, payload: dict[str, Any]) -> str:
    return f"POST {FHIR_BASE}{resource}\n{json.dumps(payload)}"


def bp_payload(mrn: str, value: str = "118/77 mmHg") -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://hl7.org/fhir/observation-category",
                        "code": "vital-signs",
                        "display": "Vital Signs",
                    }
                ]
            }
        ],
        "code": {"text": "BP"},
        "effectiveDateTime": NOW,
        "status": "final",
        "valueString": value,
        "subject": {"reference": f"Patient/{mrn}"},
    }


def referral_payload(mrn: str) -> dict[str, Any]:
    return {
        "resourceType": "ServiceRequest",
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": "306181000000106"}]},
        "authoredOn": NOW,
        "status": "active",
        "intent": "order",
        "priority": "stat",
        "note": {"text": ORTHO_NOTE},
        "subject": {"reference": f"Patient/{mrn}"},
    }


def age_of(mrn: str) -> int:
    bundle = json.loads(str(FHIR.get(f"{FHIR_BASE}Patient?identifier={mrn}&_format=json").data))
    born = datetime.strptime(bundle["entry"][0]["resource"]["birthDate"], "%Y-%m-%d")
    today = datetime(2023, 11, 13)
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


# --- read tasks -------------------------------------------------------------------------------------------------


def test_task1_oracle_is_graded_correct() -> None:
    case = TASKS["task1_1"]
    result = play(
        "task1_1", [f"GET {FHIR_BASE}Patient?name=Peter&birthdate=1932-12-29", f"FINISH({json.dumps(case['sol'])})"]
    )
    assert grade(case, result) is True


def test_task1_wrong_answer_is_graded_incorrect() -> None:
    assert grade(TASKS["task1_1"], play("task1_1", ['FINISH(["S0000000"])'])) is False


def test_task2_oracle_age_is_graded_correct() -> None:
    mrn = TASKS["task2_1"]["eval_MRN"]
    result = play("task2_1", [f"GET {FHIR_BASE}Patient?identifier={mrn}", f"FINISH([{age_of(mrn)}])"])
    assert grade(TASKS["task2_1"], result) is True


def test_task2_off_by_one_age_is_graded_incorrect() -> None:
    mrn = TASKS["task2_1"]["eval_MRN"]
    assert grade(TASKS["task2_1"], play("task2_1", [f"FINISH([{age_of(mrn) + 1}])"])) is False


def test_an_unfinished_run_is_incorrect() -> None:
    result = play("task1_1", ["I do not know"])
    assert result.status is Status.INVALID_ACTION and grade(TASKS["task1_1"], result) is False


# --- the POST-text rule on read-only tasks ----------------------------------------------------------------------


def test_any_post_text_fails_a_read_only_task_even_when_the_gate_rejected_it() -> None:
    case = TASKS["task1_1"]
    rejected = {"resourceType": "ServiceRequest"}  # fails the spec gate, so no POST is ever accepted
    result = play("task1_1", [post("ServiceRequest", rejected), f"FINISH({json.dumps(case['sol'])})"], WITH_VALIDATION)
    assert result.rejected_posts == 1
    assert grade(case, result) is False


# --- write tasks, and the gates must not block grader-correct answers --------------------------------------------


@pytest.mark.parametrize("cfg", [REFERENCE, WITH_VALIDATION, FULL], ids=["reference", "validation", "full"])
def test_task3_oracle_write_is_graded_correct_and_never_blocked(cfg: GateConfig) -> None:
    mrn = TASKS["task3_1"]["eval_MRN"]
    result = play("task3_1", [post("Observation", bp_payload(mrn)), "FINISH([])"], cfg)
    assert result.rejected_posts == 0
    assert grade(TASKS["task3_1"], result) is True


def test_task3_wrong_value_is_graded_incorrect() -> None:
    mrn = TASKS["task3_1"]["eval_MRN"]
    result = play("task3_1", [post("Observation", bp_payload(mrn, "120/80 mmHg")), "FINISH([])"])
    assert grade(TASKS["task3_1"], result) is False


def test_task3_without_any_write_is_graded_incorrect() -> None:
    assert grade(TASKS["task3_1"], play("task3_1", ["FINISH([])"])) is False


@pytest.mark.parametrize("cfg", [REFERENCE, WITH_VALIDATION, FULL], ids=["reference", "validation", "full"])
def test_task8_oracle_referral_is_graded_correct_and_never_blocked(cfg: GateConfig) -> None:
    mrn = TASKS["task8_1"]["eval_MRN"]
    result = play("task8_1", [post("ServiceRequest", referral_payload(mrn)), "FINISH([])"], cfg)
    assert result.rejected_posts == 0
    assert grade(TASKS["task8_1"], result) is True


def test_a_rejected_write_then_a_corrected_one_still_grades_correct() -> None:
    mrn = TASKS["task3_1"]["eval_MRN"]
    incomplete = {k: v for k, v in bp_payload(mrn).items() if k != "valueString"}
    result = play(
        "task3_1",
        [post("Observation", incomplete), post("Observation", bp_payload(mrn)), "FINISH([])"],
        WITH_VALIDATION,
    )
    assert result.rejected_posts == 1
    assert grade(TASKS["task3_1"], result) is True


def test_a_correct_write_without_a_finish_is_incorrect_like_in_the_reference_harness() -> None:
    """The grader only inspects the POSTs for write tasks, so the harness-level rule must reject unfinished runs."""
    mrn = TASKS["task3_1"]["eval_MRN"]
    result = play("task3_1", [post("Observation", bp_payload(mrn)), "I am done"])
    assert result.status is Status.INVALID_ACTION and result.result is None
    assert grade(TASKS["task3_1"], result) is False


def test_threads_grading_at_once_share_one_loaded_grader() -> None:
    """Concurrent first use must not build the grader twice: a thread could see it half loaded (no task9 yet)."""
    import importlib
    import threading

    import medgate.grade as grade_module

    importlib.reload(grade_module)  # forget any cached load so the threads race on a cold start
    seen: list[Any] = []

    def load() -> None:
        seen.append(grade_module._grader())  # noqa: SLF001 - the loader is the thing under test

    threads = [threading.Thread(target=load) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(seen) == 8 and all(g is seen[0] for g in seen) and hasattr(seen[0], "task9")
