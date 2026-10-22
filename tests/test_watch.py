"""Pure tests for the results watch: which results count as new, and the task the agent gets for each. No network."""

import json
from pathlib import Path
from typing import Any

import pytest

from medgate.fhir import GetResult
from medgate.watch import Event, Protocol, Ward, case_for, load_ward, new_results

BASE = "http://localhost:8080/fhir/"
NOW = "2023-11-13T10:15:00+00:00"
POTASSIUM = Protocol("Potassium replacement", "K", "If potassium is below 3.5, order replacement.")
MAGNESIUM = Protocol("Magnesium replacement", "MG", "If magnesium is below 2, order replacement.")


def observation(id_: str, code: str, when: str, value: float) -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "id": id_,
        "meta": {"versionId": "1"},
        "code": {"coding": [{"system": "http://loinc.org", "code": code, "display": code}], "text": code},
        "effectiveDateTime": when,
        "valueQuantity": {"value": value, "unit": "mmol/L"},
    }


class FakeFhir:
    """Canned Observation searches by (patient, code)."""

    base = BASE

    def __init__(self, results: dict[tuple[str, str], list[dict[str, Any]]], fail: bool = False) -> None:
        self.results = results
        self.fail = fail

    def get(self, url: str) -> GetResult:
        if self.fail:
            return GetResult(error="500 Server Error")
        query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
        rows = self.results.get((query["patient"], query["code"]), [])
        return GetResult(data=json.dumps({"resourceType": "Bundle", "entry": [{"resource": r} for r in rows]}))


def ward(*patients: str, window_hours: float = 24) -> Ward:
    return Ward(NOW, window_hours, patients, (POTASSIUM, MAGNESIUM))


def test_the_newest_covered_result_inside_the_window_is_an_event() -> None:
    fhir = FakeFhir(
        {
            ("S1", "K"): [
                observation("old", "K", "2023-11-01T08:00:00+00:00", 4.0),
                observation("new", "K", "2023-11-13T06:00:00+00:00", 3.1),
            ]
        }
    )
    (event,) = new_results(ward("S1"), fhir)  # type: ignore[arg-type]
    assert (event.patient, event.protocol.code, event.result["id"]) == ("S1", "K", "new")
    assert event.result["valueQuantity"] == {"value": 3.1, "unit": "mmol/L"} and "meta" not in event.result


def test_a_newest_result_older_than_the_window_is_not_new() -> None:
    fhir = FakeFhir({("S1", "K"): [observation("old", "K", "2023-11-11T10:14:00+00:00", 3.0)]})
    assert new_results(ward("S1"), fhir) == []  # type: ignore[arg-type]
    assert new_results(ward("S1", window_hours=48), fhir) == []  # type: ignore[arg-type]  # 48 h and 1 min old
    assert len(new_results(ward("S1", window_hours=49), fhir)) == 1  # type: ignore[arg-type]


def test_a_result_exactly_at_the_window_edge_counts() -> None:
    fhir = FakeFhir({("S1", "K"): [observation("edge", "K", "2023-11-12T10:15:00+00:00", 3.3)]})
    assert len(new_results(ward("S1"), fhir)) == 1  # type: ignore[arg-type]


def test_results_dated_after_now_are_ignored() -> None:
    fhir = FakeFhir(
        {
            ("S1", "K"): [
                observation("today", "K", "2023-11-13T06:00:00+00:00", 3.9),
                observation("future", "K", "2023-11-14T06:00:00+00:00", 2.5),
            ]
        }
    )
    (event,) = new_results(ward("S1"), fhir)  # type: ignore[arg-type]
    assert event.result["id"] == "today"


def test_every_patient_and_protocol_is_checked_and_absent_results_give_no_event() -> None:
    fhir = FakeFhir(
        {
            ("S1", "K"): [observation("a", "K", "2023-11-13T06:00:00+00:00", 3.1)],
            ("S1", "MG"): [observation("b", "MG", "2023-11-13T07:00:00+00:00", 1.8)],
            ("S2", "MG"): [observation("c", "MG", "2023-11-12T23:00:00+00:00", 2.1)],
        }
    )
    events = new_results(ward("S1", "S2", "S3"), fhir)  # type: ignore[arg-type]
    assert [(e.patient, e.protocol.code) for e in events] == [("S1", "K"), ("S1", "MG"), ("S2", "MG")]
    assert [e.patient for e in new_results(ward("S1", "S2"), fhir, patients=["S2"])] == ["S2"]  # type: ignore[arg-type]


def test_a_failed_search_raises_instead_of_skipping_the_patient() -> None:
    with pytest.raises(RuntimeError, match="could not search K results for S1"):
        new_results(ward("S1"), FakeFhir({}, fail=True))  # type: ignore[arg-type]


def test_the_agent_gets_the_protocol_as_context_and_the_result_as_the_question() -> None:
    event = Event(
        "S1",
        POTASSIUM,
        {"id": "obs9", "code": "K", "effectiveDateTime": NOW, "valueQuantity": {"value": 3.1, "unit": "mmol/L"}},
    )
    case = case_for(event, NOW)
    assert case["id"] == "watch:S1:K"
    assert case["context"] == f"It's {NOW} now. {POTASSIUM.text}"
    assert "patient S1: K 3.1 mmol/L" in case["instruction"] and "(Observation/obs9)" in case["instruction"]
    assert "citing this result" in case["instruction"]


def test_the_demo_ward_loads() -> None:
    loaded = load_ward(Path(__file__).resolve().parents[1] / "demo" / "ward.json")
    assert loaded.now == NOW and loaded.window_hours == 24 and len(loaded.patients) == 7
    assert [p.code for p in loaded.protocols] == ["K", "MG"]
