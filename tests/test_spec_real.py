"""The spec gate against the benchmark's real tool definitions: grader-correct payloads must never be flagged."""

from typing import Any

import pytest

from medgate import gates
from medgate.tasks import DEFAULT_DATA, load_functions

if not (DEFAULT_DATA / "funcs_v1.json").exists():
    pytest.skip("needs vendor/MedAgentBench", allow_module_level=True)

FUNCS = load_functions()
NOW = "2023-11-13T10:15:00+00:00"
SUBJECT = {"reference": "Patient/S1"}
BASE = "http://localhost:8080/fhir/"


def medication(route: Any, dose: float = 2) -> dict[str, Any]:
    return {
        "resourceType": "MedicationRequest",
        "medicationCodeableConcept": {"coding": [{"system": "http://hl7.org/fhir/sid/ndc", "code": "0338-1715-40"}]},
        "authoredOn": NOW,
        "dosageInstruction": [
            {
                "route": route,
                "doseAndRate": [
                    {"doseQuantity": {"value": dose, "unit": "g"}, "rateQuantity": {"value": 2, "unit": "h"}}
                ],
            }
        ],
        "status": "active",
        "intent": "order",
        "subject": SUBJECT,
    }


def service_request(code: str = "4548-4", **extra: Any) -> dict[str, Any]:
    return {
        "resourceType": "ServiceRequest",
        "code": {"coding": [{"system": "http://loinc.org", "code": code}]},
        "authoredOn": NOW,
        "status": "active",
        "intent": "order",
        "priority": "stat",
        "subject": SUBJECT,
        **extra,
    }


GRADER_CORRECT = {
    "task3 blood pressure": (
        "Observation",
        {
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
            "valueString": "118/77 mmHg",
            "subject": SUBJECT,
        },
    ),
    "task5 IV magnesium (route as string, as the grader requires)": ("MedicationRequest", medication("IV")),
    "task5 route written as the spec says (object)": ("MedicationRequest", medication({"text": "IV"})),
    "task8 referral with note object": ("ServiceRequest", service_request("306181000000106", note={"text": "x"})),
    "task9 oral potassium (route as string)": ("MedicationRequest", medication("oral", dose=40.0)),
    "task9 morning potassium level": (
        "ServiceRequest",
        service_request("2823-3", occurrenceDateTime="2023-11-14T08:00:00+00:00"),
    ),
    "task10 A1C order": ("ServiceRequest", service_request()),
}


@pytest.mark.parametrize("name", sorted(GRADER_CORRECT))
def test_grader_correct_payloads_pass_the_spec_gate(name: str) -> None:
    resource, payload = GRADER_CORRECT[name]
    assert gates.spec_problems(f"{BASE}{resource}", payload, FUNCS) == []


@pytest.mark.parametrize("field", ["intent", "priority", "subject", "authoredOn", "status", "code"])
def test_every_required_service_request_field_is_enforced(field: str) -> None:
    payload = {k: v for k, v in service_request().items() if k != field}
    assert any(f"required field {field!r}" in p for p in gates.spec_problems(f"{BASE}ServiceRequest", payload, FUNCS))


def test_wrong_nesting_is_flagged_with_a_readable_path() -> None:
    payload = service_request()
    payload["code"] = {"coding": {"code": "4548-4"}}  # coding must be an array
    assert "code.coding: expected array, got dict" in gates.spec_problems(f"{BASE}ServiceRequest", payload, FUNCS)


def test_string_where_a_number_is_required_is_flagged() -> None:
    payload = medication("IV", dose="2")  # type: ignore[arg-type]
    problems = gates.spec_problems(f"{BASE}MedicationRequest", payload, FUNCS)
    assert "dosageInstruction[].doseAndRate[].doseQuantity.value: expected number, got str" in problems


def test_missing_observation_fields_are_all_reported() -> None:
    problems = gates.spec_problems(f"{BASE}Observation", {"resourceType": "Observation"}, FUNCS)
    assert len(problems) == 6 and all("required field" in p for p in problems)
