"""Search results on the live server: what the agent sees must contain what the tasks ask about, on every task.

The expected readings are computed here from the server's full result set, independently of the code under test.
"""

import json
from datetime import datetime, timedelta
from typing import Any

import pytest

from medgate.fhir import FhirClient
from medgate.gates import FORMAT_ONLY
from medgate.llm import ScriptedLlm, ToolCall, Turn
from medgate.protocol import FHIR_BASE
from medgate.results import MAX_CHARS, NO_RESULTS
from medgate.tasks import load_functions, load_tasks
from medgate.tool_agent import run_tool_task

pytestmark = pytest.mark.live
FHIR = FhirClient()
if not FHIR.is_up():
    pytest.skip("FHIR server is not running on localhost:8080", allow_module_level=True)

FUNCS = load_functions()
NOW = datetime.fromisoformat("2023-11-13T10:15:00+00:00")  # the time every task states
CODE_OF = {"task4": "MG", "task5": "MG", "task6": "GLU", "task7": "GLU", "task9": "K", "task10": "A1C"}
READ_TASKS = [t for t in load_tasks() if t["id"].split("_")[0] in CODE_OF]
PATIENT = "S3241217"  # has records of every searchable type


def tool_reply(case: dict[str, Any], tool: str, arguments: dict[str, Any]) -> str:
    """The text the agent is shown for one search, through the real tool loop."""
    turns = [
        Turn(calls=(ToolCall("s", tool, json.dumps(arguments)),)),
        Turn(calls=(ToolCall("f", "finish", '{"answer": []}'),)),
    ]
    result = run_tool_task(case, FUNCS, ScriptedLlm(turns), FHIR, FORMAT_ONLY)
    return next(m["content"] for m in result.transcript if m["role"] == "tool")


def all_readings(mrn: str, code: str) -> list[tuple[datetime, str, float]]:
    url = f"{FHIR_BASE}Observation?patient={mrn}&code={code}&_count=5000&_format=json"
    resources = [e["resource"] for e in json.loads(str(FHIR.get(url).data)).get("entry", [])]
    return [
        (datetime.fromisoformat(r["effectiveDateTime"]), r["effectiveDateTime"], r["valueQuantity"]["value"])
        for r in resources
    ]


def test_every_read_task_shows_the_newest_reading_and_the_whole_last_day() -> None:
    misses: list[str] = []
    for case in READ_TASKS:
        mrn, code = case["eval_MRN"], CODE_OF[case["id"].split("_")[0]]
        readings = all_readings(mrn, code)
        reply = tool_reply(case, "observation_search_labs", {"patient": mrn, "code": code})
        lines = reply.split("\n")
        assert len(reply) <= MAX_CHARS + 300, case["id"]
        if not readings:
            assert lines[0].startswith("0 results."), case["id"]
            continue
        newest = max(readings)
        first = json.loads(lines[1])
        if (first["effectiveDateTime"], first["valueQuantity"]["value"]) != (newest[1], newest[2]):
            misses.append(f"{case['id']}: newest not first")
        last_day = [r for r in readings if r[0] >= NOW - timedelta(hours=24)]
        rows = [json.loads(line) for line in lines[1:]]
        shown = {(row["effectiveDateTime"], row["valueQuantity"]["value"]) for row in rows}
        misses += [f"{case['id']}: {t} missing" for _, t, v in last_day if (t, v) not in shown]
    assert misses == [] and len(READ_TASKS) == 180


def test_a_search_with_the_ordering_code_instead_of_the_lab_code_says_what_to_try() -> None:
    """GPT-4.1 searched potassium by the LOINC ordering code 2823-3, found nothing and stopped (Phase 7)."""
    case = {"id": "x", "context": "", "instruction": f"patient {PATIENT}"}
    reply = tool_reply(case, "observation_search_labs", {"patient": PATIENT, "code": "2823-3"})
    assert reply == NO_RESULTS


def test_rendered_labs_keep_exact_times_numeric_values_and_references() -> None:
    case = {"id": "x", "context": "", "instruction": f"patient {PATIENT}"}
    reply = tool_reply(case, "observation_search_labs", {"patient": PATIENT, "code": "K"})
    raw = {r[1]: r[2] for r in all_readings(PATIENT, "K")}
    rows = [json.loads(line) for line in reply.split("\n")[1:]]
    assert len(rows) == len(raw) and all(raw[row["effectiveDateTime"]] == row["valueQuantity"]["value"] for row in rows)
    assert all(isinstance(row["valueQuantity"]["value"], int | float) for row in rows)
    assert all(row["subject"] == f"Patient/{PATIENT}" and "meta" not in row for row in rows)


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("observation_search_vitals", {"category": "vital-signs"}),
        ("medicationrequest_search_signed_medication_order", {}),
        ("procedure_search_orders", {"date": "ge2000-01-01"}),
        ("condition_search_problems", {}),  # the spec says category=problem-list-item, but no record has a category
        ("patient_search", {"identifier": PATIENT}),
    ],
)
def test_every_searchable_type_renders_compact_lines(tool: str, arguments: dict[str, Any]) -> None:
    case = {"id": "x", "context": "", "instruction": f"patient {PATIENT}"}
    patient = {} if tool == "patient_search" else {"patient": PATIENT}
    reply = tool_reply(case, tool, {**patient, **arguments})
    header, *lines = reply.split("\n")
    assert header.split(" ")[0].isdigit() and int(header.split(" ")[0]) > 0 and lines
    rows = [json.loads(line) for line in lines]
    assert all("meta" not in row and "text" not in row or isinstance(row.get("text"), str) for row in rows)
    assert '"system":"http' not in reply and '"div"' not in reply
    assert PATIENT in reply  # the patient id or reference survives compaction
    if tool != "patient_search":
        assert header.split(", ")[1].startswith("newest first")
