"""The watch's order tool can carry how often and how long a medication is given; the benchmark's cannot."""

from typing import Any

from medgate.gates import spec_problems
from medgate.tasks import load_functions, watch_functions

ORDER = "POST {api_base}/MedicationRequest"
URL = "http://localhost:8080/fhir/MedicationRequest"


def _dosage(functions: list[dict[str, Any]]) -> dict[str, Any]:
    tool = next(t for t in functions if t["name"] == ORDER)
    return tool["parameters"]["properties"]["dosageInstruction"]["items"]["properties"]


def test_benchmark_tool_is_unchanged_and_the_watch_tool_adds_timing() -> None:
    assert "timing" not in _dosage(load_functions())
    assert "timing" in _dosage(watch_functions())
    assert "timing" not in _dosage(load_functions())  # building the watch's copy does not touch the benchmark's


def test_the_watch_medication_tool_has_a_priority_the_benchmark_one_lacks() -> None:
    tool = next(t for t in watch_functions() if t["name"] == ORDER)
    assert "priority" in tool["parameters"]["properties"]
    assert "priority" not in next(t for t in load_functions() if t["name"] == ORDER)["parameters"]["properties"]


def test_payload_gate_accepts_and_checks_the_timing_fields() -> None:
    def payload(frequency: Any) -> dict[str, Any]:
        timing = {
            "repeat": {
                "frequency": frequency,
                "period": 1,
                "periodUnit": "d",
                "boundsDuration": {"value": 2, "unit": "d"},
            }
        }
        return {
            "resourceType": "MedicationRequest",
            "medicationCodeableConcept": {"coding": [{"code": "0904-6301-60"}]},
            "authoredOn": "2023-11-13T10:15:00+00:00",
            "dosageInstruction": [
                {"route": "oral", "doseAndRate": [{"doseQuantity": {"value": 1, "unit": "g"}}], "timing": timing}
            ],
            "status": "active",
            "intent": "order",
            "subject": {"reference": "Patient/S1"},
        }

    functions = watch_functions()
    assert spec_problems(URL, payload(2), functions) == []
    assert spec_problems(URL, payload("twice"), functions) != []


def test_time_gate_rejects_the_malformed_times_seen_in_model_output() -> None:
    from medgate.gates import time_problems

    assert (
        time_problems({"authoredOn": "2023-11-13T10:15:00+00:00", "occurrenceDateTime": "2023-11-14T08:00:00Z"}) == []
    )
    assert time_problems({"authoredOn": "2023-11-11-13T10:15:00+00:00"}) != []
    assert time_problems({"occurrenceDateTime": "2023-11-13T10:10:45:00+00:00"}) != []
    assert time_problems({"occurrenceDateTime": "2023-11-13T10:45:00"}) != []  # no zone
    assert time_problems("not a payload") == []


def test_field_check_is_added_to_the_review_only_when_asked() -> None:
    from medgate.tool_agent import FIELD_CHECK, review_message

    assert FIELD_CHECK not in review_message([])
    assert FIELD_CHECK in review_message([], field_check=True)


def test_the_watch_requires_a_route_and_a_dose_but_the_benchmark_tool_does_not() -> None:
    order: dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "medicationCodeableConcept": {"text": "x"},
        "authoredOn": "2023-11-13T10:15:00+00:00",
        "status": "active",
        "intent": "order",
        "subject": {"reference": "S1"},
        "dosageInstruction": [{"doseAndRate": [{"doseQuantity": {"value": 1, "unit": "g"}}]}],
    }
    assert any("route" in p for p in spec_problems(URL, order, watch_functions()))
    assert not spec_problems(URL, order, load_functions())
    order["dosageInstruction"] = [
        {"route": {"text": "IV"}, "doseAndRate": [{"rateQuantity": {"value": 1, "unit": "h"}}]}
    ]
    assert any("doseQuantity" in p for p in spec_problems(URL, order, watch_functions()))
    order["dosageInstruction"] = [
        {"route": {"text": "IV"}, "doseAndRate": [{"doseQuantity": {"value": 1, "unit": "g"}}]}
    ]
    assert not spec_problems(URL, order, watch_functions())
