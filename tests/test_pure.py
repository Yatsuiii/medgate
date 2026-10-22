"""Pure tests: protocol parsing, gates, and the loop against a fake FHIR server. No network."""

import json
from typing import Any

import pytest

from medgate import gates
from medgate.fhir import GetResult
from medgate.gates import FORMAT_ONLY, FULL, REFERENCE, WITH_VALIDATION, GateConfig
from medgate.llm import ScriptedLlm
from medgate.loop import Status, run_task
from medgate.protocol import (
    GET_ERROR,
    GET_RESPONSE,
    POST_ACCEPTED,
    POST_INVALID,
    Finish,
    Get,
    Invalid,
    Post,
    build_prompt,
    parse_reply,
)

CASE = {"id": "task9_1", "instruction": "Order a test for patient S100", "context": "", "sol": []}
FUNCS: list[dict[str, Any]] = [
    {
        "name": "POST {api_base}/ServiceRequest",
        "parameters": {
            "type": "object",
            "required": ["resourceType", "subject", "status"],
            "properties": {
                "resourceType": {"type": "string"},
                "status": {"type": "string"},
                "subject": {"type": "object", "properties": {"reference": {"type": "string"}}},
                "note": {"type": "object", "properties": {"text": {"type": "string"}}},
                "coding": {"type": "array", "items": {"type": "object", "properties": {"code": {"type": "string"}}}},
            },
        },
    }
]
GOOD = {"resourceType": "ServiceRequest", "status": "active", "subject": {"reference": "Patient/S100"}}
GOOD_POST = f"POST http://localhost:8080/fhir/ServiceRequest\n{json.dumps(GOOD)}"
URL = "http://localhost:8080/fhir/ServiceRequest"


class FakeFhir:
    """Duck-typed stand-in for FhirClient with canned GET responses."""

    def __init__(self, gets: dict[str, GetResult] | None = None) -> None:
        self.gets = gets or {}

    def get(self, url: str) -> GetResult:
        return self.gets.get(url, GetResult(error="404 Not Found"))


def run(replies: list[str], cfg: GateConfig = REFERENCE, fhir: FakeFhir | None = None, **kw: Any):
    llm = ScriptedLlm(replies)
    return run_task(CASE, FUNCS, llm, fhir or FakeFhir(), cfg, **kw), llm  # type: ignore[arg-type]


def roles(result: Any) -> list[str]:
    return [m["role"] for m in result.history]


# --- protocol ---------------------------------------------------------------------------------------------------


def test_parse_get_appends_format_json() -> None:
    assert parse_reply("GET http://x/fhir/Patient?name=A") == Get("http://x/fhir/Patient?name=A&_format=json")


def test_parse_strips_code_fences() -> None:
    assert parse_reply("```tool_code\nGET http://x/p?a=1\n```") == Get("http://x/p?a=1&_format=json")


def test_parse_post_with_json_payload() -> None:
    assert parse_reply('POST http://x/fhir/ServiceRequest\n{"a": 1}') == Post("http://x/fhir/ServiceRequest", {"a": 1})


def test_parse_post_with_invalid_json_has_no_payload() -> None:
    assert parse_reply("POST http://x/fhir/ServiceRequest\n{oops").payload is None  # type: ignore[union-attr]


def test_parse_finish_slices_like_the_reference() -> None:
    assert parse_reply('FINISH(["S1"])') == Finish('["S1"]')


@pytest.mark.parametrize("text", ["I think the answer is 5", "", "get http://x", "FINISH"])
def test_parse_anything_else_is_invalid(text: str) -> None:
    assert isinstance(parse_reply(text), Invalid)


def test_prompt_contains_question_context_and_tools() -> None:
    prompt = build_prompt({"instruction": "Q?", "context": "C!"}, FUNCS, "http://base/")
    assert "Question: Q?" in prompt and "Context: C!" in prompt and "http://base/" in prompt
    assert "ServiceRequest" in prompt


# --- gates ------------------------------------------------------------------------------------------------------


def test_presets_are_nested() -> None:
    assert not any([REFERENCE.format_retry, REFERENCE.validate_payload, REFERENCE.require_evidence])
    assert FORMAT_ONLY.format_retry and not FORMAT_ONLY.validate_payload
    assert WITH_VALIDATION.validate_payload and not WITH_VALIDATION.require_evidence
    assert FULL.require_evidence


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://h/fhir/ServiceRequest", "ServiceRequest"),
        ("http://h/fhir/Observation?x=1", "Observation"),
        ("http://h/fhir/MedicationRequest/", "MedicationRequest"),
        ("http://h/fhir/Patient", None),
    ],
)
def test_resource_type_of(url: str, expected: str | None) -> None:
    assert gates.resource_type_of(url) == expected


def test_spec_accepts_a_conforming_payload() -> None:
    assert gates.spec_problems(URL, GOOD, FUNCS) == []


def test_spec_rejects_unwritable_resources_and_non_objects() -> None:
    assert gates.spec_problems("http://h/fhir/Patient", {}, FUNCS) != []
    assert gates.spec_problems(URL, [1], FUNCS) == ["the payload must be a JSON object"]


def test_spec_requires_matching_resource_type() -> None:
    assert "must be 'ServiceRequest'" in gates.spec_problems(URL, {**GOOD, "resourceType": "Observation"}, FUNCS)[0]


def test_spec_flags_missing_required_fields_with_a_path() -> None:
    problems = gates.spec_problems(URL, {"resourceType": "ServiceRequest"}, FUNCS)
    assert "payload: required field 'subject' is missing" in problems
    assert "payload: required field 'status' is missing" in problems


def test_spec_flags_wrong_types_with_a_path() -> None:
    bad = {**GOOD, "note": "free text", "subject": {"reference": 5}, "coding": [{"code": ["x"]}]}
    problems = gates.spec_problems(URL, bad, FUNCS)
    assert "note: expected object, got str" in problems
    assert "subject.reference: expected string, got int" in problems
    assert "coding[].code: expected string, got list" in problems


def test_spec_does_not_treat_booleans_as_numbers() -> None:
    funcs = [{"name": "POST {api_base}/Observation", "parameters": {"properties": {"v": {"type": "number"}}}}]
    assert gates.spec_problems("http://h/fhir/Observation", {"resourceType": "Observation", "v": True}, funcs) != []
    assert gates.spec_problems("http://h/fhir/Observation", {"resourceType": "Observation", "v": 1.5}, funcs) == []


def test_spec_skips_the_documented_spec_grader_conflict() -> None:
    funcs = [
        {
            "name": "POST {api_base}/MedicationRequest",
            "parameters": {
                "type": "object",
                "properties": {
                    "dosageInstruction": {
                        "type": "array",
                        "items": {"type": "object", "properties": {"route": {"type": "object"}}},
                    }
                },
            },
        }
    ]
    payload = {"resourceType": "MedicationRequest", "dosageInstruction": [{"route": "IV"}]}
    assert gates.spec_problems("http://h/fhir/MedicationRequest", payload, funcs) == []


def test_evidence_found_in_text_or_missing() -> None:
    payload = {"subject": {"reference": "Patient/S100"}, "performer": [{"reference": "Practitioner/P7"}]}
    assert gates.evidence_problems(payload, "patient S100 and P7") == []
    problems = gates.evidence_problems(payload, "patient S100 only")
    assert len(problems) == 1 and "Practitioner/P7" in problems[0]


def test_rejection_message_shows_at_most_three_problems() -> None:
    message = gates.rejection_message(["P1", "P2", "P3", "P4"])
    assert "P1; P2; P3" in message and "P4" not in message


# --- reference loop (all gates off) -----------------------------------------------------------------------------


def test_reference_get_then_finish() -> None:
    fhir = FakeFhir({"u&_format=json": GetResult(data="BUNDLE")})
    result, _ = run(["GET u", 'FINISH(["x"])'], fhir=fhir)
    assert result.status is Status.COMPLETED and result.result == '["x"]'
    assert roles(result) == ["user", "agent", "user", "agent"]
    assert result.history[2]["content"] == GET_RESPONSE.format(data="BUNDLE")


def test_reference_get_error_is_reported_to_the_agent() -> None:
    result, _ = run(["GET missing", "FINISH([])"])
    assert result.history[2]["content"] == GET_ERROR.format(error="404 Not Found")


def test_reference_invalid_action_ends_the_task() -> None:
    result, _ = run(["thinking out loud"])
    assert result.status is Status.INVALID_ACTION and result.result is None and roles(result) == ["user", "agent"]


def test_reference_accepts_any_valid_json_post() -> None:
    result, _ = run(['POST http://h/fhir/ServiceRequest\n{"anything": true}', "FINISH([])"])
    assert result.history[2]["content"] == POST_ACCEPTED


def test_reference_invalid_json_post_is_reported() -> None:
    result, _ = run(["POST http://h/fhir/ServiceRequest\n{oops", "FINISH([])"])
    assert result.history[2]["content"] == POST_INVALID


def test_reference_round_limit() -> None:
    result, llm = run(["GET u"] * 8)
    assert result.status is Status.LIMIT_REACHED and len(llm.seen) == 8


# --- gates inside the loop --------------------------------------------------------------------------------------


def test_format_retry_continues_and_counts() -> None:
    result, _ = run(["hmm", "FINISH([])"], FORMAT_ONLY)
    assert result.status is Status.COMPLETED and result.format_retries == 1
    assert result.history[2]["content"] == gates.FORMAT_RETRY


def test_format_retry_still_respects_the_round_limit() -> None:
    result, llm = run(["hmm"] * 20, FORMAT_ONLY)
    assert result.status is Status.LIMIT_REACHED and len(llm.seen) == 8


def test_validation_rejects_a_payload_missing_required_fields_then_accepts_the_fix() -> None:
    bad = 'POST http://localhost:8080/fhir/ServiceRequest\n{"resourceType":"ServiceRequest"}'
    result, _ = run([bad, GOOD_POST, "FINISH([])"], WITH_VALIDATION)
    assert result.rejected_posts == 1
    assert result.history[2]["content"].startswith("POST request rejected")
    assert "'subject' is missing" in result.history[2]["content"]
    assert result.history[4]["content"] == POST_ACCEPTED


def test_validation_is_off_in_the_reference_and_format_only_arms() -> None:
    bad = 'POST http://localhost:8080/fhir/ServiceRequest\n{"resourceType":"ServiceRequest"}'
    for cfg in (REFERENCE, FORMAT_ONLY):
        result, _ = run([bad, "FINISH([])"], cfg)
        assert result.rejected_posts == 0 and result.history[2]["content"] == POST_ACCEPTED


def test_evidence_gate_blocks_unretrieved_reference() -> None:
    post = {**GOOD, "subject": {"reference": "Patient/S999"}}
    result, _ = run([f"POST {URL}\n{json.dumps(post)}", "FINISH([])"], FULL)
    assert result.rejected_posts == 1 and "S999" in result.history[2]["content"]


def test_evidence_gate_allows_reference_from_question_or_retrieval() -> None:
    post = {**GOOD, "subject": {"reference": "Patient/S999"}}
    fhir = FakeFhir({"u&_format=json": GetResult(data="patient S999 found")})
    result, _ = run(["GET u", f"POST {URL}\n{json.dumps(post)}", "FINISH([])"], FULL, fhir)
    assert result.rejected_posts == 0 and result.history[4]["content"] == POST_ACCEPTED
    result2, _ = run([GOOD_POST, "FINISH([])"], FULL)  # S100 is named in the question
    assert result2.rejected_posts == 0


def test_rejected_post_is_invisible_to_a_history_based_grader() -> None:
    """Rebuilds the reference grader's extract_posts rule: only POSTs answered with the accepted message count."""
    bad = 'POST http://localhost:8080/fhir/ServiceRequest\n{"resourceType":"ServiceRequest"}'
    result, _ = run([bad, GOOD_POST, "FINISH([])"], WITH_VALIDATION)
    posts = []
    for idx, message in enumerate(result.history):
        if message["role"] == "agent" and "POST" in message["content"]:
            if idx + 1 < len(result.history) and "POST request accepted" in result.history[idx + 1]["content"]:
                lines = message["content"].split("\n")
                posts.append(json.loads("\n".join(lines[1:])))
    assert posts == [GOOD]


def test_gates_that_never_trigger_leave_the_conversation_identical_to_the_reference() -> None:
    replies = [GOOD_POST, 'FINISH(["done"])']
    reference, _ = run(replies, REFERENCE)
    gated, _ = run(replies, FULL)
    assert reference.history == gated.history and reference.result == gated.result
