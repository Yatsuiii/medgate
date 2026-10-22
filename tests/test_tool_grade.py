"""The tool-calling arms against the real benchmark grader: scripted oracle agents on the live FHIR server.

Each oracle plays what a correct agent would do with the tools. The expected values are computed here from the live
records, independently of the grader, and both arms must be graded correct: T because the grader's view of a tool
run must match the reference protocol, TG because the gates must never block a correct run.
"""

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from medgate.cli import main
from medgate.fhir import FhirClient
from medgate.gates import FORMAT_ONLY, FULL, GateConfig
from medgate.grade import GRADER, grade
from medgate.llm import ScriptedLlm, ToolCall, Turn
from medgate.loop import TaskResult
from medgate.protocol import FHIR_BASE
from medgate.tasks import load_functions, load_tasks
from medgate.tool_agent import run_tool_task

pytestmark = pytest.mark.live
FHIR = FhirClient()
if not FHIR.is_up() or not GRADER.exists():
    pytest.skip("needs the FHIR server and vendor/refsol.py", allow_module_level=True)

TASKS = load_tasks()
BY_ID = {t["id"]: t for t in TASKS}
FUNCS = load_functions()
NOW = "2023-11-13T10:15:00+00:00"
NOW_TIME = datetime.fromisoformat(NOW)
BOTH_ARMS = pytest.mark.parametrize("cfg", [FORMAT_ONLY, FULL], ids=["T", "TG"])
Reading = tuple[datetime, float, str]  # (time, value, the time exactly as the record writes it)


def step(name: str, arguments: dict[str, Any]) -> Turn:
    return Turn(calls=(ToolCall(f"call_{name}", name, json.dumps(arguments)),))


def finish(answer: list[Any]) -> Turn:
    return step("finish", {"answer": answer})


def play(case: dict[str, Any], turns: list[Turn], cfg: GateConfig) -> TaskResult:
    return run_tool_task(case, FUNCS, ScriptedLlm(turns), FHIR, cfg)


def readings(mrn: str, code: str) -> list[Reading]:
    url = f"{FHIR_BASE}Observation?patient={mrn}&code={code}&_count=5000&_format=json"
    resources = [entry["resource"] for entry in json.loads(str(FHIR.get(url).data)).get("entry", [])]
    return [
        (datetime.fromisoformat(r["effectiveDateTime"]), r["valueQuantity"]["value"], r["effectiveDateTime"])
        for r in resources
    ]


def newest(rows: list[Reading], since: datetime | None = None) -> Reading | None:
    return max((r for r in rows if since is None or r[0] >= since), default=None)


def first_case(category: str, wanted: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    case = next((c for c in TASKS if c["id"].startswith(f"{category}_") and wanted(c)), None)
    if case is None:
        pytest.fail(f"no {category} case matches; the oracle needs one")
    return case


def subject(case: dict[str, Any]) -> dict[str, str]:
    return {"reference": f"Patient/{case['eval_MRN']}"}


def service_request(case: dict[str, Any], code: str, system: str, **extra: Any) -> dict[str, Any]:
    return {
        "code": {"coding": [{"system": system, "code": code}]},
        "authoredOn": NOW,
        "status": "active",
        "intent": "order",
        "priority": "stat",
        "subject": subject(case),
        **extra,
    }


def medication(case: dict[str, Any], ndc: str, route: str, dose: dict[str, Any], **rate: Any) -> dict[str, Any]:
    return {
        "medicationCodeableConcept": {"coding": [{"system": "http://hl7.org/fhir/sid/ndc", "code": ndc}]},
        "authoredOn": NOW,
        "dosageInstruction": [{"route": route, "doseAndRate": [{"doseQuantity": dose, **rate}]}],
        "status": "active",
        "intent": "order",
        "subject": subject(case),
    }


def assert_correct_and_never_blocked(case: dict[str, Any], result: TaskResult) -> None:
    assert (result.rejected_posts, result.rejected_reads) == (0, 0)
    assert grade(case, result) is True


# --- read tasks -------------------------------------------------------------------------------------------------


@BOTH_ARMS
def test_task1_oracle(cfg: GateConfig) -> None:
    case = BY_ID["task1_1"]
    search = step("patient_search", {"given": "Peter", "family": "Stafford", "birthdate": "1932-12-29"})
    assert_correct_and_never_blocked(case, play(case, [search, finish(case["sol"])], cfg))


def age_turns(case: dict[str, Any], age_offset: int = 0) -> list[Turn]:
    bundle = json.loads(str(FHIR.get(f"{FHIR_BASE}Patient?identifier={case['eval_MRN']}&_format=json").data))
    born = bundle["entry"][0]["resource"]["birthDate"]
    age = NOW_TIME.year - int(born[:4]) - ((NOW_TIME.month, NOW_TIME.day) < (int(born[5:7]), int(born[8:10])))
    return [
        step("patient_search", {"identifier": case["eval_MRN"]}),
        step("calculator", {"expression": f'years_between("{born}", "{NOW}")'}),
        finish([age + age_offset]),
    ]


@BOTH_ARMS
def test_task2_oracle_with_the_calculator(cfg: GateConfig) -> None:
    case = BY_ID["task2_1"]
    assert_correct_and_never_blocked(case, play(case, age_turns(case), cfg))


def test_task2_off_by_one_is_graded_incorrect() -> None:
    case = BY_ID["task2_1"]
    assert grade(case, play(case, age_turns(case, age_offset=1), FORMAT_ONLY)) is False


def test_tg_rejects_a_search_for_the_wrong_patient_and_the_corrected_run_still_grades_correct() -> None:
    case = BY_ID["task2_1"]
    result = play(case, [step("patient_search", {"identifier": "S0000000"}), *age_turns(case)], FULL)
    assert result.rejected_reads == 1 and grade(case, result) is True


@pytest.mark.parametrize("cfg", [FORMAT_ONLY, FULL], ids=["T accepts it", "TG rejects it"])
def test_a_create_call_on_a_read_only_task_fails_even_when_the_gate_rejected_it(cfg: GateConfig) -> None:
    case = BY_ID["task1_1"]
    turns = [step("servicerequest_create", {"status": "active"}), finish(case["sol"])]
    assert grade(case, play(case, turns, cfg)) is False


# --- write tasks ------------------------------------------------------------------------------------------------


@BOTH_ARMS
def test_task3_oracle_without_a_resource_type(cfg: GateConfig) -> None:
    case = BY_ID["task3_1"]
    category = {"system": "http://hl7.org/fhir/observation-category", "code": "vital-signs", "display": "Vital Signs"}
    vitals = {
        "category": [{"coding": [category]}],
        "code": {"text": "BP"},
        "effectiveDateTime": NOW,
        "status": "final",
        "valueString": "118/77 mmHg",
        "subject": subject(case),
    }
    assert_correct_and_never_blocked(case, play(case, [step("observation_create_vitals", vitals), finish([])], cfg))


def magnesium_today(case: dict[str, Any]) -> Reading | None:
    return newest(readings(case["eval_MRN"], "MG"), since=NOW_TIME - timedelta(hours=24))


@BOTH_ARMS
def test_task5_oracle_orders_iv_magnesium_when_low(cfg: GateConfig) -> None:
    case = first_case("task5", lambda c: (r := magnesium_today(c)) is not None and r[1] <= 1.9)
    reading = magnesium_today(case)
    assert reading is not None
    grams = 1 if reading[1] >= 1.5 else 2 if reading[1] >= 1 else 4
    order = medication(
        case, "0338-1715-40", "IV", {"value": grams, "unit": "g"}, rateQuantity={"value": grams, "unit": "h"}
    )
    turns = [
        step("observation_search_labs", {"patient": case["eval_MRN"], "code": "MG", "_sort": "-date"}),
        step("medicationrequest_create", order),
        finish([reading[1]]),
    ]
    assert_correct_and_never_blocked(case, play(case, turns, cfg))


@BOTH_ARMS
def test_task5_oracle_orders_nothing_when_magnesium_is_normal_or_missing(cfg: GateConfig) -> None:
    case = first_case("task5", lambda c: (r := magnesium_today(c)) is None or r[1] > 1.9)
    reading = magnesium_today(case)
    turns = [
        step("observation_search_labs", {"patient": case["eval_MRN"], "code": "MG", "_sort": "-date"}),
        finish([reading[1] if reading else -1]),
    ]
    assert_correct_and_never_blocked(case, play(case, turns, cfg))


@BOTH_ARMS
def test_task8_oracle_referral(cfg: GateConfig) -> None:
    case = BY_ID["task8_1"]
    note = case["instruction"].split('"')[1]  # the referral text the task quotes
    referral = service_request(case, "306181000000106", "http://snomed.info/sct", note={"text": note})
    assert_correct_and_never_blocked(case, play(case, [step("servicerequest_create", referral), finish([])], cfg))


@BOTH_ARMS
def test_task9_oracle_orders_potassium_and_a_morning_level_when_low(cfg: GateConfig) -> None:
    case = first_case("task9", lambda c: (r := newest(readings(c["eval_MRN"], "K"))) is not None and r[1] < 3.5)
    reading = newest(readings(case["eval_MRN"], "K"))
    assert reading is not None
    dose = (3.5 - reading[1]) / 0.1 * 10
    turns = [
        step("observation_search_labs", {"patient": case["eval_MRN"], "code": "K", "_sort": "-date", "_count": 1}),
        step("calculator", {"expression": f"(3.5 - {reading[1]}) / 0.1 * 10"}),
        step("medicationrequest_create", medication(case, "40032-917-01", "oral", {"value": dose, "unit": "mEq"})),
        step(
            "servicerequest_create",
            service_request(case, "2823-3", "http://loinc.org", occurrenceDateTime="2023-11-14T08:00:00+00:00"),
        ),
        finish([reading[1]]),
    ]
    assert_correct_and_never_blocked(case, play(case, turns, cfg))


def a1c_is_due(case: dict[str, Any]) -> bool:
    reading = newest(readings(case["eval_MRN"], "A1C"))
    return reading is None or reading[0] < NOW_TIME - timedelta(days=365)


def a1c_answer(case: dict[str, Any]) -> list[Any]:
    reading = newest(readings(case["eval_MRN"], "A1C"))
    return [-1] if reading is None else [reading[1], reading[2]]


@BOTH_ARMS
def test_task10_oracle_orders_a1c_when_due(cfg: GateConfig) -> None:
    case = first_case("task10", a1c_is_due)
    turns = [
        step("observation_search_labs", {"patient": case["eval_MRN"], "code": "A1C", "_sort": "-date"}),
        step("servicerequest_create", service_request(case, "4548-4", "http://loinc.org")),
        finish(a1c_answer(case)),
    ]
    assert_correct_and_never_blocked(case, play(case, turns, cfg))


@BOTH_ARMS
def test_task10_oracle_reports_a_recent_a1c_without_ordering(cfg: GateConfig) -> None:
    case = first_case("task10", lambda c: not a1c_is_due(c))
    turns = [
        step("observation_search_labs", {"patient": case["eval_MRN"], "code": "A1C", "_sort": "-date"}),
        finish(a1c_answer(case)),
    ]
    assert_correct_and_never_blocked(case, play(case, turns, cfg))


# --- command line -----------------------------------------------------------------------------------------------


def test_cli_dry_run_for_the_tool_arms_and_compare(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for arm in ("T", "TG"):
        out = str(tmp_path / f"{arm}.jsonl")
        assert main(["run", "--arm", arm, "--model", "dry", "--out", out, "--limit", "3", "--dry-run"]) == 0
    capsys.readouterr()
    assert main(["compare", str(tmp_path / "T.jsonl"), str(tmp_path / "TG.jsonl")]) == 0
    output = capsys.readouterr().out
    assert "n=3" in output and "rejected searches 0" in output


def test_cli_runs_exactly_the_listed_tasks_in_order(tmp_path: Path) -> None:
    out = tmp_path / "T.jsonl"
    args = ["run", "--arm", "T", "--model", "dry", "--out", str(out), "--dry-run", "--tasks", "task9_4,task1_13"]
    assert main(args) == 0
    assert [json.loads(line)["task_id"] for line in out.read_text().splitlines()] == ["task9_4", "task1_13"]


def test_cli_refuses_unknown_task_ids(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["run", "--arm", "T", "--model", "dry", "--out", str(tmp_path / "x"), "--dry-run", "--tasks", "task1_99"]
    assert main(args) == 2 and "unknown task ids: task1_99" in capsys.readouterr().err
