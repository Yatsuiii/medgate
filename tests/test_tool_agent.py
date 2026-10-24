"""Pure tests for the tool-calling arms: tool definitions, the calculator, the loop and the API client. No network."""

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from medgate import calculator, gates
from medgate.calculator import CalculatorError
from medgate.fhir import GetResult
from medgate.gates import FORMAT_ONLY, FULL, REFERENCE, WATCH, GateConfig
from medgate.llm import OpenAiCompatibleLlm, ScriptedLlm, ToolCall, Turn
from medgate.loop import Status, TaskResult
from medgate.protocol import GET_RESPONSE, POST_ACCEPTED, POST_INVALID
from medgate.results import MAX_CHARS
from medgate.runner import run_arm
from medgate.tasks import DEFAULT_DATA, load_functions
from medgate.tool_agent import RE_REVIEW, REMINDER, REVIEW, REVIEW_ROUNDS, review_message, run_tool_task
from medgate.tools import FETCH_ALL, fhir_tools, search_url, tool_definitions

BASE = "http://localhost:8080/fhir/"
CASE = {"id": "task9_1", "instruction": "Order a test for patient S100", "context": "It is now.", "sol": []}
FUNCS: list[dict[str, Any]] = [
    {
        "name": "GET {api_base}/Observation",
        "description": "Observation.Search (Labs) Lab results.",
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string"}, "patient": {"type": "string"}},
            "required": ["code", "patient"],
        },
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
ORDER = {"status": "active", "subject": {"reference": "Patient/S100"}}
SEARCH = {"code": "K", "patient": "S100"}
SEARCH_URL = f"{BASE}Observation?code=K&patient=S100&_count={FETCH_ALL}"
needs_spec = pytest.mark.skipif(not (DEFAULT_DATA / "funcs_v1.json").exists(), reason="needs vendor/MedAgentBench")


def call(name: str, arguments: Any, call_id: str = "c1") -> ToolCall:
    return ToolCall(call_id, name, arguments if isinstance(arguments, str) else json.dumps(arguments))


def turn(*calls: ToolCall, text: str = "") -> Turn:
    return Turn(text=text, calls=calls)


def finish(answer: list[Any]) -> Turn:
    return turn(call("finish", {"answer": answer}, "fin"))


class FakeFhir:
    """Duck-typed FhirClient with canned search results; records every url it was asked for."""

    base = BASE

    def __init__(self, gets: dict[str, GetResult] | None = None) -> None:
        self.gets = gets or {}
        self.asked: list[str] = []

    def get(self, url: str) -> GetResult:
        self.asked.append(url)
        return self.gets.get(url, GetResult(error="404 Not Found"))


def play(turns: list[Turn], cfg: GateConfig = FORMAT_ONLY, fhir: FakeFhir | None = None) -> tuple[TaskResult, Any]:
    llm = ScriptedLlm(turns)
    return run_tool_task(CASE, FUNCS, llm, fhir or FakeFhir(), cfg), llm  # type: ignore[arg-type]


def tool_replies(result: TaskResult) -> list[str]:
    return [m["content"] for m in result.transcript if m["role"] == "tool"]


# --- tools from the spec ----------------------------------------------------------------------------------------


def test_tool_names_come_from_the_spec_descriptions() -> None:
    assert list(fhir_tools(FUNCS)) == ["observation_search_labs", "servicerequest_create"]


def test_searches_get_sort_and_count_controls_and_writes_do_not() -> None:
    tools = fhir_tools(FUNCS)
    search = tools["observation_search_labs"].definition["function"]["parameters"]["properties"]
    write = tools["servicerequest_create"].definition["function"]["parameters"]["properties"]
    assert {"_sort", "_count", "code", "patient"} <= set(search) and "_sort" not in write


def test_definitions_add_the_calculator_and_finish() -> None:
    names = [d["function"]["name"] for d in tool_definitions(fhir_tools(FUNCS))]
    assert names == ["observation_search_labs", "servicerequest_create", "calculator", "finish"]


def test_two_spec_entries_with_one_name_are_refused() -> None:
    with pytest.raises(ValueError, match="observation_search_labs"):
        fhir_tools([FUNCS[0], FUNCS[0]])


def test_search_url_fetches_every_match_and_keeps_the_controls_for_the_results() -> None:
    tool = fhir_tools(FUNCS)["observation_search_labs"]
    assert search_url(tool, SEARCH) == SEARCH_URL
    url = search_url(tool, {**SEARCH, "date": "ge2023-11-12T10:15:00+00:00", "_sort": "date", "_count": 1, "x": ""})
    assert url == f"{BASE}Observation?code=K&patient=S100&date=ge2023-11-12T10%3A15%3A00%2B00%3A00&_count={FETCH_ALL}"


@needs_spec
def test_every_benchmark_function_becomes_a_uniquely_named_tool() -> None:
    tools = fhir_tools(load_functions())
    assert sorted(tools) == [
        "condition_search_problems",
        "medicationrequest_create",
        "medicationrequest_search_signed_medication_order",
        "observation_create_vitals",
        "observation_search_labs",
        "observation_search_vitals",
        "patient_search",
        "procedure_search_orders",
        "servicerequest_create",
    ]
    assert [t.method for t in tools.values()].count("POST") == 3


@needs_spec
def test_the_medication_route_is_typed_as_the_grader_needs_and_the_spec_is_left_alone() -> None:
    functions = load_functions()
    schema = fhir_tools(functions)["medicationrequest_create"].definition["function"]["parameters"]
    assert schema["properties"]["dosageInstruction"]["items"]["properties"]["route"] == {"type": "string"}
    original = next(f for f in functions if f["name"] == "POST {api_base}/MedicationRequest")
    assert original["parameters"]["properties"]["dosageInstruction"]["items"]["properties"]["route"]["type"] == "object"


# --- calculator -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("(3.5 - 3.1) / 0.1 * 10", 40.0),
        ("sum([120, 135, 150]) / len([120, 135, 150])", 135.0),
        ("round(1.2345, 2)", 1.23),
        ("max(1, 2.5) - min([4, -1])", 3.5),
        ("7 // 2 + 7 % 2 - -2 ** 2", 8),
        ('hours_between("2023-11-12T10:15:00+00:00", "2023-11-13T10:15:00+00:00")', 24.0),
        ('days_between("2022-11-13", "2023-11-13T00:00:00+00:00")', 365.0),
        ('years_between("1932-12-29", "2023-11-13T10:15:00+00:00")', 90),
    ],
)
def test_calculator_evaluates_what_the_tasks_need(expression: str, expected: float) -> None:
    assert calculator.evaluate(expression) == pytest.approx(expected)


@pytest.mark.parametrize(
    "expression",
    [
        "().__class__",
        "(1).__class__.__bases__",
        "__import__('os').system('true')",
        "open('/etc/passwd')",
        "x + 1",
        "lambda: 1",
        "[n for n in [1]]",
        "round(1.5, ndigits=1)",
        "2 ** 1000",
        "10 ** 6 * 10 ** 7",
        "[1] * 5",
        "'a' * 3",
        "True + 1",
        "1 / 0",
        "sqrt(-1)",
        "1 +",
        "1" * 501,
    ],
)
def test_calculator_rejects_anything_outside_the_allowlist(expression: str) -> None:
    with pytest.raises(CalculatorError):
        calculator.evaluate(expression)


@pytest.mark.parametrize("expression", ["-" * 400 + "1", "(" * 150 + "1" + ")" * 150])
def test_calculator_handles_deep_nesting_without_crashing(expression: str) -> None:
    try:
        calculator.evaluate(expression)
    except CalculatorError:
        pass


# --- the loop and the grader's view of it ------------------------------------------------------------------------


def test_a_search_is_mirrored_as_a_get_line_and_the_model_gets_the_data() -> None:
    fhir = FakeFhir({f"{SEARCH_URL}&_format=json": GetResult(data="BUNDLE S100")})
    result, _ = play([turn(call("observation_search_labs", SEARCH)), finish([3.1])], fhir=fhir)
    assert result.status is Status.COMPLETED and result.result == "[3.1]"
    assert result.history == [
        {"role": "agent", "content": f"GET {SEARCH_URL}"},
        {"role": "user", "content": GET_RESPONSE.format(data="BUNDLE S100")},
        {"role": "agent", "content": "FINISH([3.1])"},
    ]
    assert tool_replies(result)[0] == "BUNDLE S100"


def test_a_create_call_is_mirrored_as_a_post_line_with_the_resource_type_filled_in() -> None:
    result, _ = play([turn(call("servicerequest_create", ORDER)), finish([])])
    payload = {"resourceType": "ServiceRequest", **ORDER}
    assert result.history[:2] == [
        {"role": "agent", "content": f"POST {BASE}ServiceRequest\n{json.dumps(payload)}"},
        {"role": "user", "content": POST_ACCEPTED},
    ]


def test_create_arguments_that_do_not_parse_count_as_an_invalid_post() -> None:
    result, _ = play([turn(call("servicerequest_create", "{oops")), finish([])])
    assert result.history[:2] == [
        {"role": "agent", "content": f"POST {BASE}ServiceRequest\n{{oops"},
        {"role": "user", "content": POST_INVALID},
    ]


def test_free_text_stays_in_the_transcript_and_out_of_the_grader_history() -> None:
    result, _ = play([turn(call("observation_search_labs", SEARCH), text="Plan: no POST is needed."), finish([])])
    assert all("Plan" not in m["content"] for m in result.history)
    assert result.transcript[2]["role"] == "assistant" and result.transcript[2]["content"] == "Plan: no POST is needed."


def test_a_reply_without_a_tool_call_gets_a_reminder() -> None:
    result, _ = play([turn(text="Let me think."), finish([])])
    assert result.status is Status.COMPLETED and result.format_retries == 1
    assert {"role": "user", "content": REMINDER} in result.transcript


def test_without_the_format_retry_a_reply_without_a_tool_call_ends_the_task() -> None:
    result, _ = play([turn(text="done")], REFERENCE)
    assert result.status is Status.INVALID_ACTION and result.result is None


def test_the_round_limit_counts_model_calls() -> None:
    result, llm = play([turn(text="hmm")] * 20)
    assert result.status is Status.LIMIT_REACHED and len(llm.seen) == 8


def test_unknown_tools_and_bad_finish_arguments_get_errors_and_the_task_goes_on() -> None:
    result, _ = play([turn(call("delete_patient", {}), call("finish", {"answer": "4"}, "c2")), finish([4])])
    replies = tool_replies(result)
    assert replies[0].startswith("Error: there is no tool") and replies[1].startswith("Error: call finish")
    assert result.result == "[4]"


def test_calculator_results_go_to_the_model_only() -> None:
    result, _ = play([turn(call("calculator", {"expression": "(3.5 - 3.1) / 0.1 * 10"})), finish([40])])
    assert float(tool_replies(result)[0]) == pytest.approx(40)
    assert result.history == [{"role": "agent", "content": "FINISH([40])"}]


def test_a_calculator_error_is_reported_to_the_model() -> None:
    result, _ = play([turn(call("calculator", {"expression": "open('x')"})), finish([])])
    assert tool_replies(result)[0].startswith("Error: not allowed")


def test_a_long_reply_that_is_not_a_bundle_is_cut_with_a_note() -> None:
    big = "x" * (MAX_CHARS + 10)
    fhir = FakeFhir({f"{SEARCH_URL}&_format=json": GetResult(data=big)})
    result, _ = play([turn(call("observation_search_labs", SEARCH)), finish([])], fhir=fhir)
    reply = tool_replies(result)[0]
    assert reply.startswith("x" * MAX_CHARS) and "x" * (MAX_CHARS + 1) not in reply
    assert reply.endswith("Narrow the search with a date filter, _sort or _count.]")


def bundle(*times: str) -> str:
    resources = [{"resourceType": "Observation", "id": f"o{i}", "effectiveDateTime": t} for i, t in enumerate(times)]
    return json.dumps({"resourceType": "Bundle", "entry": [{"resource": r} for r in resources]})


THREE = bundle("2023-01-02T00:00:00+00:00", "2023-03-01T00:00:00+00:00", "2023-02-01T00:00:00+00:00")


@pytest.mark.parametrize(
    ("controls", "ids"),
    [({}, ["o1", "o2", "o0"]), ({"_sort": "date"}, ["o0", "o2", "o1"]), ({"_count": 1}, ["o1"])],
)
def test_results_are_newest_first_unless_the_agent_asks_otherwise(controls: dict[str, Any], ids: list[str]) -> None:
    fhir = FakeFhir({f"{SEARCH_URL}&_format=json": GetResult(data=THREE)})
    result, _ = play([turn(call("observation_search_labs", {**SEARCH, **controls})), finish([])], fhir=fhir)
    lines = tool_replies(result)[0].split("\n")
    assert lines[0].startswith("3 results") and [json.loads(line)["id"] for line in lines[1:]] == ids
    assert fhir.asked == [f"{SEARCH_URL}&_format=json"]  # the controls never reach the server


def test_calls_after_finish_in_the_same_reply_are_not_run() -> None:
    fhir = FakeFhir()
    turns = [turn(call("finish", {"answer": []}, "f"), call("observation_search_labs", SEARCH, "s"))]
    result, _ = play(turns, fhir=fhir)
    assert result.status is Status.COMPLETED and fhir.asked == []


# --- the check at finish ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        ["4.2"],
        ["-1"],
        [90, "4.2 mg/dL"],
        ["10mEq"],
        ["90 years"],
        ["The most recent CBG of patient S2823623 is 191 mg/dL."],
        [{"last_hba1c_value": 5.9, "recorded": "2023-11-09T03:05:00+00:00"}],
        [[-1]],
    ],
)
def test_an_answer_that_is_not_plain_values_gets_one_nudge_and_then_is_accepted_as_is(answer: list[Any]) -> None:
    result, _ = play([finish(answer), finish(answer)])
    assert result.status is Status.COMPLETED and result.result == json.dumps(answer)
    assert result.format_retries == 1 and tool_replies(result)[0].startswith("Check the answer:")


def test_a_corrected_answer_after_the_nudge_is_the_one_recorded() -> None:
    result, _ = play([finish(["4.2"]), finish([4.2])])
    assert result.result == "[4.2]" and result.history == [{"role": "agent", "content": "FINISH([4.2])"}]


@pytest.mark.parametrize(
    "answer",
    [[4.2], [-1], ["S6534835"], ["Patient not found"], ["118/77 mmHg"], [6.1, "2023-01-05T09:30:00+00:00"], []],
)
def test_well_formed_answers_are_never_nudged(answer: list[Any]) -> None:
    result, _ = play([finish(answer)])
    assert result.status is Status.COMPLETED and result.format_retries == 0


# --- the finish-time review (arm WATCH) -------------------------------------------------------------------------


def review_replies(result: TaskResult) -> list[str]:
    return [r for r in tool_replies(result) if r.startswith(REVIEW[:40])]


def test_with_the_review_off_a_finish_with_no_orders_completes_at_once() -> None:
    for cfg in (REFERENCE, FORMAT_ONLY, FULL):
        result, llm = play([finish([])], cfg)
        assert result.status in (Status.COMPLETED, Status.INVALID_ACTION) and len(llm.seen) <= 1
        assert not review_replies(result)


def test_the_review_shows_that_no_orders_were_created_and_the_second_finish_completes() -> None:
    result, llm = play([finish([]), finish([])], WATCH)
    assert result.status is Status.COMPLETED and len(llm.seen) == 2
    (review,) = review_replies(result)
    assert review == review_message([]) and review.endswith("You have created no orders.")
    assert result.history == [{"role": "agent", "content": "FINISH([])"}]  # the review is not in the graded history
    assert result.format_retries == 0


def test_the_review_lists_the_orders_created_so_far_and_a_later_order_is_recorded() -> None:
    other = {"status": "active", "subject": {"reference": "Patient/S100"}, "priority": "stat"}
    result, _ = play(
        [
            turn(call("servicerequest_create", ORDER)),
            finish([]),
            turn(call("servicerequest_create", other)),
            finish([]),
            finish([]),
        ],
        WATCH,
    )
    (review,) = review_replies(result)
    assert json.dumps({"resourceType": "ServiceRequest", **ORDER}) in review and "priority" not in review
    posts = [m["content"] for m in result.history if m["role"] == "agent" and m["content"].startswith("POST")]
    assert len(posts) == 2 and result.status is Status.COMPLETED


def test_the_review_fires_once_however_often_the_model_finishes() -> None:
    result, llm = play([finish([]), finish([]), finish([])], WATCH)
    assert len(review_replies(result)) == 1 and len(llm.seen) == 2  # the second finish completes the task


def re_review_replies(result: TaskResult) -> list[str]:
    return [r for r in tool_replies(result) if r.startswith(RE_REVIEW[:40])]


def test_an_order_written_after_the_review_gets_one_more_review_of_the_whole_list() -> None:
    other = {"status": "active", "subject": {"reference": "Patient/S100"}, "priority": "stat"}
    result, llm = play(
        [
            turn(call("servicerequest_create", ORDER)),
            finish([]),
            turn(call("servicerequest_create", other)),
            finish([]),
            turn(call("servicerequest_create", other, "c3")),
            finish([]),
        ],
        WATCH,
    )
    (again,) = re_review_replies(result)
    assert again.startswith(RE_REVIEW) and json.dumps({"resourceType": "ServiceRequest", **ORDER}) in again
    assert '"priority": "stat"' in again  # the order written after the first review is in the list
    assert result.status is Status.COMPLETED and len(llm.seen) == 6  # a third order is not reviewed a third time


def test_no_new_order_after_the_review_means_no_second_review() -> None:
    result, _ = play([turn(call("servicerequest_create", ORDER)), finish([]), finish([])], WATCH)
    assert not re_review_replies(result) and result.status is Status.COMPLETED


def test_a_badly_formatted_first_finish_is_nudged_before_the_review_and_the_nudge_counts_as_a_retry() -> None:
    result, _ = play([finish(["4.2"]), finish([4.2]), finish([4.2])], WATCH)
    replies = tool_replies(result)
    assert replies[0].startswith("Check the answer:") and replies[1].startswith(REVIEW[:40])
    assert result.format_retries == 1 and result.result == "[4.2]"


def test_the_review_does_not_use_up_the_round_limit() -> None:
    searches = [turn(call("observation_search_labs", SEARCH, f"s{i}")) for i in range(7)]
    result, _ = play(
        [*searches, finish([]), finish([])], WATCH, fhir=FakeFhir({f"{SEARCH_URL}&_format=json": GetResult(data="B")})
    )
    assert (
        result.status is Status.COMPLETED
    )  # 7 searches, a finish, the review, a finish: 9 model calls, limit is 8 + 3
    assert REVIEW_ROUNDS == 6


def test_a_prose_only_reply_after_the_review_gets_the_reminder_and_the_task_still_completes() -> None:
    result, _ = play([finish([]), turn(text="The protocol requires none."), finish([])], WATCH)
    assert result.status is Status.COMPLETED and result.format_retries == 1
    assert {"role": "user", "content": REMINDER} in result.transcript


def test_the_review_text_names_no_drug_number_or_order_type() -> None:
    banned = r"\b(potassium|magnesium|mg|meq|stat|paired|1\.9|3\.5)\b"
    assert not re.search(banned, REVIEW.lower()) and "is missing" not in REVIEW.lower().replace(
        "something is missing", ""
    )


# --- gates in the tool loop (TG) --------------------------------------------------------------------------------


def test_tg_rejects_a_create_missing_a_required_field() -> None:
    result, _ = play([turn(call("servicerequest_create", {"subject": ORDER["subject"]})), finish([])], FULL)
    assert result.rejected_posts == 1 and "'status' is missing" in result.history[1]["content"]
    assert tool_replies(result)[0].startswith("POST request rejected")


def test_tg_rejects_a_search_for_a_patient_never_seen_and_does_not_run_it() -> None:
    fhir = FakeFhir()
    result, _ = play([turn(call("observation_search_labs", {"code": "K", "patient": "S999"})), finish([])], FULL, fhir)
    assert result.rejected_reads == 1 and fhir.asked == []
    assert result.history[1]["content"].startswith("Search rejected: patient='S999'")


def test_tg_allows_a_search_for_the_patient_in_the_question() -> None:
    fhir = FakeFhir({f"{SEARCH_URL}&_format=json": GetResult(data="B")})
    result, _ = play([turn(call("observation_search_labs", SEARCH)), finish([])], FULL, fhir)
    assert result.rejected_reads == 0 and fhir.asked == [f"{SEARCH_URL}&_format=json"]


def test_tg_rejects_a_write_for_a_patient_never_seen_and_t_accepts_it() -> None:
    order = {"status": "active", "subject": {"reference": "Patient/S999"}}
    gated, _ = play([turn(call("servicerequest_create", order)), finish([])], FULL)
    plain, _ = play([turn(call("servicerequest_create", order)), finish([])], FORMAT_ONLY)
    assert gated.rejected_posts == 1 and "S999" in gated.history[1]["content"]
    assert plain.rejected_posts == 0 and plain.history[1]["content"] == POST_ACCEPTED


def test_tg_evidence_grows_with_what_the_agent_retrieved() -> None:
    fhir = FakeFhir({f"{SEARCH_URL}&_format=json": GetResult(data="results mention Patient/S777")})
    order = {"status": "active", "subject": {"reference": "Patient/S777"}}
    turns = [turn(call("observation_search_labs", SEARCH)), turn(call("servicerequest_create", order)), finish([])]
    result, _ = play(turns, FULL, fhir)
    assert result.rejected_posts == 0


def test_read_problems_look_only_at_patient_scoped_parameters() -> None:
    assert gates.read_problems({"patient": "Patient/S100", "code": "K"}, "S100") == []
    assert gates.read_problems({"given": "Peter", "birthdate": "1932-12-29"}, "") == []
    assert len(gates.read_problems({"identifier": "S5", "subject": "Patient/S6"}, "S100")) == 2


# --- the model interface ----------------------------------------------------------------------------------------


def test_a_turn_renders_as_an_assistant_message_with_its_tool_calls() -> None:
    assert Turn(calls=(ToolCall("a", "finish", "{}"),)).message() == {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "a", "type": "function", "function": {"name": "finish", "arguments": "{}"}}],
    }


def test_the_scripted_llm_refuses_the_wrong_kind_of_reply() -> None:
    with pytest.raises(AssertionError):
        ScriptedLlm(["text"]).chat([], [])
    with pytest.raises(AssertionError):
        ScriptedLlm([Turn()]).complete([])


def api(tmp_path: Path, reply: dict[str, Any], sent: list[dict[str, Any]], **kw: Any) -> OpenAiCompatibleLlm:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer k3y"
        assert str(request.url) == "https://api.example/v1/chat/completions"
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": reply}]})

    key = tmp_path / "key"
    key.write_text("k3y\n")
    transport = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAiCompatibleLlm("https://api.example/v1/", "nvidia/m", key_file=key, http=transport, **kw)


def test_chat_sends_tools_and_sampling_and_parses_tool_calls(tmp_path: Path) -> None:
    sent: list[dict[str, Any]] = []
    reply = {
        "content": None,
        "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "finish", "arguments": '{"answer": [1]}'}},
            {"type": "function", "function": {"name": "calculator", "arguments": {"expression": "1+1"}}},
        ],
    }
    llm = api(tmp_path, reply, sent, temperature=1.0, top_p=0.95)
    result = llm.chat([{"role": "user", "content": "hi"}], [{"type": "function", "function": {"name": "finish"}}])
    assert sent[0]["model"] == "nvidia/m" and sent[0]["temperature"] == 1.0 and sent[0]["top_p"] == 0.95
    assert sent[0]["tools"] == [{"type": "function", "function": {"name": "finish"}}]
    assert result == Turn(
        text="",
        calls=(ToolCall("a", "finish", '{"answer": [1]}'), ToolCall("call_1", "calculator", '{"expression": "1+1"}')),
    )


def test_chat_returns_text_when_the_model_calls_no_tool(tmp_path: Path) -> None:
    assert api(tmp_path, {"content": "thinking"}, []).chat([], []) == Turn(text="thinking")


def test_complete_sends_the_same_request_as_before(tmp_path: Path) -> None:
    sent: list[dict[str, Any]] = []
    llm = api(tmp_path, {"content": "FINISH([])"}, sent)
    assert llm.complete([{"role": "user", "content": "q"}, {"role": "agent", "content": "GET x"}]) == "FINISH([])"
    assert sent == [
        {
            "model": "nvidia/m",
            "temperature": 0.0,
            "messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "GET x"}],
        }
    ]


# --- runner -----------------------------------------------------------------------------------------------------


def test_run_arm_runs_tool_arms_with_the_tool_loop_and_records_the_transcript(tmp_path: Path) -> None:
    case = {"id": "task1_1", "instruction": "Q", "context": "", "sol": []}
    records = run_arm(
        "T",
        "m",
        [case],
        FUNCS,
        lambda: ScriptedLlm([finish(["x"])]),
        FakeFhir(),  # type: ignore[arg-type]
        tmp_path / "T.jsonl",
        grader=lambda c, r: r.result == '["x"]',
    )
    assert records[0]["correct"] is True and records[0]["arm"] == "T"
    assert records[0]["transcript"][0]["role"] == "system" and records[0]["rejected_reads"] == 0
