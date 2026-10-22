"""Pure tests for the review step: proposals from a run, cited evidence, FHIR conversion and commit. No network."""

import json
from typing import Any

import pytest

from medgate.fhir import GetResult
from medgate.gates import FORMAT_ONLY, FULL
from medgate.llm import ScriptedLlm, ToolCall, Turn
from medgate.review import Proposal, commit, proposals, to_fhir
from medgate.tool_agent import run_tool_task

BASE = "http://localhost:8080/fhir/"
CASE = {"id": "task9_1", "instruction": "Order a test for patient S100", "context": "", "sol": []}
FUNCS: list[dict[str, Any]] = [
    {
        "name": "GET {api_base}/Observation",
        "description": "Observation.Search (Labs) Lab results.",
        "parameters": {"type": "object", "properties": {"code": {"type": "string"}, "patient": {"type": "string"}}},
    },
    {
        "name": "POST {api_base}/ServiceRequest",
        "description": "ServiceRequest.Create",
        "parameters": {
            "type": "object",
            "required": ["resourceType", "subject", "status"],
            "properties": {
                "resourceType": {"type": "string"},
                "status": {"type": "string"},
                "subject": {"type": "object", "properties": {"reference": {"type": "string"}}},
            },
        },
    },
]
OBSERVATION = {
    "resourceType": "Observation",
    "id": "o1",
    "meta": {"versionId": "1"},
    "code": {"coding": [{"system": "http://loinc.org", "code": "K", "display": "K"}], "text": "K"},
    "effectiveDateTime": "2023-11-12T20:36:00+00:00",
    "valueQuantity": {"value": 3.1, "unit": "mmol/L", "system": "http://unitsofmeasure.org", "code": "mmol/L"},
}


class FakeFhir:
    """Duck-typed FhirClient: canned reads, and a store that can be told to drop one field, as a lenient server does."""

    base = BASE

    def __init__(self, gets: dict[str, GetResult] | None = None, drop: str | None = None) -> None:
        self.gets = gets or {}
        self.drop = drop
        self.created: list[dict[str, Any]] = []

    def get(self, url: str) -> GetResult:
        return self.gets.get(url, GetResult(error="404 Not Found"))

    def create(self, resource_type: str, payload: dict[str, Any]) -> str:
        self.created.append(json.loads(json.dumps(payload)))
        return f"{resource_type}/{len(self.created)}"

    def read(self, reference: str) -> dict[str, Any]:
        stored = json.loads(json.dumps(self.created[int(reference.split("/")[1]) - 1]))
        if self.drop:
            stored["dosageInstruction"][0].pop(self.drop)
        return {"id": reference.split("/")[1], "meta": {"versionId": "1"}, **stored}


def write(payload: Any, call_id: str = "w") -> Turn:
    arguments = payload if isinstance(payload, str) else json.dumps(payload)
    return Turn(calls=(ToolCall(call_id, "servicerequest_create", arguments),))


def finish() -> Turn:
    return Turn(calls=(ToolCall("f", "finish", '{"answer": []}'),))


def medication(route: Any) -> Proposal:
    payload = {
        "resourceType": "MedicationRequest",
        "status": "active",
        "dosageInstruction": [{"route": route, "doseAndRate": [{"doseQuantity": {"value": 40, "unit": "mEq"}}]}],
    }
    return Proposal("MedicationRequest", payload, None, ())


def test_every_attempted_write_becomes_a_proposal_with_what_the_gates_found() -> None:
    good = {"status": "active", "subject": {"reference": "Patient/S100"}}
    turns = [write({"subject": {"reference": "Patient/S100"}}, "a"), write("{oops", "b"), write(good, "c"), finish()]
    result = run_tool_task(CASE, FUNCS, ScriptedLlm(turns), FakeFhir(), FULL)  # type: ignore[arg-type]
    found = proposals(result.history, FakeFhir())  # type: ignore[arg-type]
    assert [p.resource for p in found] == ["ServiceRequest", "ServiceRequest"]  # the unparsable write leaves nothing
    assert found[0].findings is not None and "'status' is missing" in found[0].findings
    assert found[1].findings is None and found[1].payload == {"resourceType": "ServiceRequest", **good}


@pytest.mark.parametrize("cfg", [FORMAT_ONLY, FULL], ids=["T", "TG"])
def test_a_run_never_writes_to_the_server(cfg: Any) -> None:
    fhir = FakeFhir()
    good = {"status": "active", "subject": {"reference": "Patient/S100"}}
    run_tool_task(CASE, FUNCS, ScriptedLlm([write(good), finish()]), fhir, cfg)  # type: ignore[arg-type]
    assert fhir.created == []


def test_cited_records_are_read_back_in_compact_form() -> None:
    cited = {
        "status": "active",
        "subject": {"reference": "Patient/S100"},
        "reasonReference": [{"reference": "Observation/o1"}, {"reference": "Observation/gone"}],
    }
    fhir = FakeFhir({f"{BASE}Observation/o1?_format=json": GetResult(data=json.dumps(OBSERVATION))})
    result = run_tool_task(CASE, FUNCS, ScriptedLlm([write(cited), finish()]), fhir, FORMAT_ONLY)  # type: ignore[arg-type]
    (proposal,) = proposals(result.history, fhir)  # type: ignore[arg-type]
    assert json.loads(proposal.evidence[0]) == {
        "resourceType": "Observation",
        "id": "o1",
        "code": "K",
        "effectiveDateTime": "2023-11-12T20:36:00+00:00",
        "valueQuantity": {"value": 3.1, "unit": "mmol/L"},
    }
    assert proposal.evidence[1].startswith("Observation/gone: could not be read")


def test_to_fhir_converts_the_two_benchmark_shapes_and_nothing_else() -> None:
    route = medication("oral").payload
    assert to_fhir("MedicationRequest", route)["dosageInstruction"][0]["route"] == {"text": "oral"}
    assert route["dosageInstruction"][0]["route"] == "oral"  # the proposal itself is left as the agent wrote it
    assert to_fhir("MedicationRequest", medication({"text": "IV"}).payload) == medication({"text": "IV"}).payload
    assert to_fhir("ServiceRequest", {"note": {"text": "x"}}) == {"note": [{"text": "x"}]}
    assert to_fhir("Observation", {"note": {"text": "x"}}) == {"note": {"text": "x"}}


def test_commit_sends_conformant_fhir_and_reports_a_clean_round_trip() -> None:
    fhir = FakeFhir()
    committed = commit(medication("oral"), fhir)  # type: ignore[arg-type]
    assert fhir.created[0]["dosageInstruction"][0]["route"] == {"text": "oral"}
    assert committed.reference == "MedicationRequest/1" and committed.dropped == ()


def test_commit_reports_what_the_server_did_not_store() -> None:
    committed = commit(medication("oral"), FakeFhir(drop="route"))  # type: ignore[arg-type]
    assert committed.dropped == ("dosageInstruction[0].route",)


def test_commit_refuses_a_write_the_gates_rejected_unless_overridden() -> None:
    rejected = Proposal("ServiceRequest", {"status": "active"}, "POST request rejected: x", ())
    fhir = FakeFhir()
    with pytest.raises(ValueError, match="the gates rejected this write"):
        commit(rejected, fhir)  # type: ignore[arg-type]
    assert fhir.created == []
    assert commit(rejected, fhir, override=True).reference == "ServiceRequest/1"  # type: ignore[arg-type]


def draft(resource: str, code: str, note: str = "", findings: str | None = None, field: str = "code") -> Proposal:
    return Proposal(resource, {field: {"coding": [{"code": code}]}, "note": note}, findings, (), False)


def test_a_later_draft_with_the_same_resource_and_code_supersedes_the_earlier_one_and_nothing_is_removed() -> None:
    from medgate.review import mark_superseded

    first, other, again = (
        draft("ServiceRequest", "2823-3", "a"),
        draft("ServiceRequest", "999"),
        draft("ServiceRequest", "2823-3", "b"),
    )
    marked = mark_superseded([first, other, again])
    assert [p.superseded for p in marked] == [True, False, False] and [p.payload for p in marked] == [
        first.payload,
        other.payload,
        again.payload,
    ]


def test_supersession_needs_the_same_resource_type_a_code_and_a_draft_the_gates_accepted() -> None:
    from medgate.review import mark_superseded

    med = draft("MedicationRequest", "0338-1715-40", field="medicationCodeableConcept")
    same_code_other_resource = draft("ServiceRequest", "0338-1715-40")
    rejected_later = draft(
        "MedicationRequest", "0338-1715-40", findings="'status' is missing", field="medicationCodeableConcept"
    )
    no_code_a, no_code_b = (
        Proposal("ServiceRequest", {"note": "x"}, None, (), False),
        Proposal("ServiceRequest", {"note": "y"}, None, (), False),
    )
    assert [p.superseded for p in mark_superseded([med, same_code_other_resource])] == [False, False]
    assert [p.superseded for p in mark_superseded([med, rejected_later])] == [
        False,
        False,
    ]  # a rejected draft replaces nothing
    assert [p.superseded for p in mark_superseded([rejected_later, med])] == [
        False,
        False,
    ]  # and is never itself marked
    assert [p.superseded for p in mark_superseded([no_code_a, no_code_b])] == [False, False]


def test_proposals_of_a_run_come_back_marked() -> None:
    from medgate.gates import FORMAT_ONLY as CFG

    order = {"status": "active", "subject": {"reference": "Patient/S100"}, "code": {"coding": [{"code": "X1"}]}}
    revised = {**order, "note": "fixed"}
    turns = [Turn(calls=(ToolCall("a", "servicerequest_create", json.dumps(p)),)) for p in (order, revised)]
    turns.append(Turn(calls=(ToolCall("f", "finish", '{"answer": []}'),)))
    result = run_tool_task(CASE, FUNCS, ScriptedLlm(turns), FakeFhir(), CFG)  # type: ignore[arg-type]
    marked = proposals(result.history, FakeFhir())  # type: ignore[arg-type]
    assert [p.superseded for p in marked] == [True, False]
