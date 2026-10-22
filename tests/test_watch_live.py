"""The results watch on the live server: the demo ward's new results, and the watch path graded by the benchmark.

The benchmark's task 9 (potassium) and task 5 (magnesium) are this workflow: a result comes back, a protocol says what
to order. So a watch run for a benchmark patient can be graded by the benchmark's own grader against its own case.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from medgate import review
from medgate.fhir import FhirClient
from medgate.gates import FULL
from medgate.grade import GRADER, grade
from medgate.protocol import FHIR_BASE
from medgate.tasks import load_functions, load_tasks
from medgate.tool_agent import run_tool_task
from medgate.watch import case_for, load_ward, new_results
from medgate.web import load_replay

pytestmark = pytest.mark.live
FHIR = FhirClient()
if not FHIR.is_up() or not GRADER.exists():
    pytest.skip("needs the FHIR server and vendor/refsol.py", allow_module_level=True)

DEMO = Path(__file__).resolve().parents[1] / "demo"
WARD = load_ward(DEMO / "ward.json")
REPLAY = load_replay(DEMO / "replay.json")
FUNCS = load_functions()
CATEGORY_OF = {"K": "task9", "MG": "task5"}  # the benchmark task that is this protocol
HELD = (
    "S0722219",
    "MG",
)  # low magnesium, eGFR 41: the demo protocol's renal exclusion holds it, the benchmark's does not


def newest_recent(mrn: str, code: str) -> str | None:
    """The id of the newest result in the window, computed here independently of medgate.watch."""
    now = datetime.fromisoformat(WARD.now)
    url = f"{FHIR_BASE}Observation?patient={mrn}&code={code}&_count=5000&_format=json"
    rows = [e["resource"] for e in json.loads(str(FHIR.get(url).data)).get("entry", [])]
    rows = [r for r in rows if datetime.fromisoformat(r["effectiveDateTime"]) <= now]
    if not rows:
        return None
    newest = max(rows, key=lambda r: datetime.fromisoformat(r["effectiveDateTime"]))
    recent = datetime.fromisoformat(newest["effectiveDateTime"]) >= now - timedelta(hours=WARD.window_hours)
    return str(newest["id"]) if recent else None


def test_the_watch_finds_exactly_the_new_results_on_the_demo_ward() -> None:
    expected = {
        (mrn, p.code, found) for mrn in WARD.patients for p in WARD.protocols if (found := newest_recent(mrn, p.code))
    }
    events = new_results(WARD, FHIR)
    assert {(e.patient, e.protocol.code, str(e.result["id"])) for e in events} == expected
    assert len(events) == 12


def benchmark_case(mrn: str, code: str) -> dict[str, Any] | None:
    category = CATEGORY_OF[code]
    return next((c for c in load_tasks() if c["id"].startswith(f"{category}_") and c["eval_MRN"] == mrn), None)


def test_watch_runs_for_benchmark_patients_are_graded_correct_and_cite_their_result() -> None:
    graded: list[tuple[str, str, bool]] = []
    for event in new_results(WARD, FHIR):
        case = benchmark_case(event.patient, event.protocol.code)
        if case is None:
            continue
        watch_case = case_for(event, WARD.now)
        result = run_tool_task(watch_case, FUNCS, REPLAY.llm_for(watch_case), FHIR, FULL)
        assert grade(case, result) is True, f"{event.patient} {event.protocol.code}"
        proposals = review.proposals(result.history, FHIR)
        for proposal in proposals:
            assert proposal.findings is None
            assert proposal.payload["reasonReference"] == [{"reference": f"Observation/{event.result['id']}"}]
            assert json.loads(proposal.evidence[0])["id"] == event.result["id"]
        graded.append((event.patient, event.protocol.code, bool(proposals)))
    assert ("K", True) in {(code, ordered) for _, code, ordered in graded}  # the low potassium, two orders
    assert {("MG", True), ("MG", False)} <= {(code, ordered) for _, code, ordered in graded}


def test_the_renal_exclusion_holds_magnesium_after_checking_egfr_and_orders_nothing() -> None:
    event = next(e for e in new_results(WARD, FHIR) if (e.patient, e.protocol.code) == HELD)
    assert event.result["valueQuantity"]["value"] == 1.7  # low: without the exclusion the protocol orders 1 g
    case = case_for(event, WARD.now)
    result = run_tool_task(case, FUNCS, REPLAY.llm_for(case), FHIR, FULL)
    assert result.status.value == "completed" and review.proposals(result.history, FHIR) == []
    assert any("code=EGFR" in m["content"] for m in result.history if m["content"].startswith("GET "))
    assert "held for pharmacist review" in str(result.transcript)


def test_the_other_low_magnesium_runs_check_egfr_first_and_still_order() -> None:
    for event in new_results(WARD, FHIR):
        if event.protocol.code != "MG" or (event.patient, "MG") == HELD:
            continue
        if event.result["valueQuantity"]["value"] > 1.9:
            continue
        case = case_for(event, WARD.now)
        result = run_tool_task(case, FUNCS, REPLAY.llm_for(case), FHIR, FULL)
        assert any("code=EGFR" in m["content"] for m in result.history if m["content"].startswith("GET "))
        assert len(review.proposals(result.history, FHIR)) == 1
