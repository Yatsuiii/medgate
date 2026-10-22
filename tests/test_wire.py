"""The model client and the runner over real HTTP, against a local fake chat-completions endpoint.

The fake reproduces what real endpoints do that a mock transport does not: closes with 429 and 5xx, answers with null
content, puts reasoning in the reply, and returns tool arguments that are not valid JSON.
"""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from medgate.llm import LlmError, OpenAiCompatibleLlm, ToolCall, Turn
from medgate.runner import run_arm
from medgate.tasks import load_functions, load_tasks


class FakeEndpoint:
    """Answers each POST with the next scripted (status, body, headers) and records what it was sent."""

    def __init__(self, replies: list[tuple[int, Any, dict[str, str]]]) -> None:
        self.replies = replies
        self.requests: list[dict[str, Any]] = []
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - the name http.server dispatches on
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                endpoint.requests.append({"path": self.path, "auth": self.headers["Authorization"], "body": body})
                status, payload, headers = endpoint.replies.pop(0)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for name, value in headers.items():
                    self.send_header(name, value)
                data = json.dumps(payload).encode()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signature fixed by http.server
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}/v1"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def ok(message: dict[str, Any]) -> tuple[int, Any, dict[str, str]]:
    return 200, {"choices": [{"message": message}]}, {}


@pytest.fixture
def endpoint_for() -> Iterator[Any]:
    made: list[FakeEndpoint] = []

    def make(*replies: tuple[int, Any, dict[str, str]]) -> FakeEndpoint:
        made.append(FakeEndpoint(list(replies)))
        return made[-1]

    yield make
    for endpoint in made:
        endpoint.close()


@pytest.fixture
def key_file(tmp_path: Path) -> Path:
    path = tmp_path / "key"
    path.write_text("k3y\n")
    return path


def client(endpoint: FakeEndpoint, key_file: Path, sleeps: list[float] | None = None, **kw: Any) -> OpenAiCompatibleLlm:
    record = sleeps if sleeps is not None else []
    return OpenAiCompatibleLlm(endpoint.url, "nvidia/m", key_file=key_file, sleep=record.append, **kw)


def test_the_request_carries_model_sampling_tools_and_key(endpoint_for: Any, key_file: Path) -> None:
    endpoint = endpoint_for(ok({"content": "hi"}))
    tools = [{"type": "function", "function": {"name": "finish"}}]
    llm = client(endpoint, key_file, temperature=1.0, top_p=0.95, max_tokens=4096)
    llm.chat([{"role": "user", "content": "q"}], tools)
    (sent,) = endpoint.requests
    assert sent["path"] == "/v1/chat/completions" and sent["auth"] == "Bearer k3y"
    assert sent["body"] == {
        "model": "nvidia/m",
        "temperature": 1.0,
        "top_p": 0.95,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": "q"}],
        "tools": tools,
    }


def test_null_content_in_a_text_reply_is_empty_not_the_word_none(endpoint_for: Any, key_file: Path) -> None:
    assert client(endpoint_for(ok({"content": None})), key_file).complete([{"role": "user", "content": "q"}]) == ""


def test_reasoning_in_think_tags_is_dropped_from_text_replies(endpoint_for: Any, key_file: Path) -> None:
    reply = ok({"content": "<think>GET is right\nFINISH([1])</think>\nGET http://x/Patient"})
    llm = client(endpoint_for(reply, reply), key_file)
    assert llm.complete([{"role": "user", "content": "q"}]) == "GET http://x/Patient"
    assert llm.chat([], []) == Turn(text="GET http://x/Patient")


def test_a_closing_think_tag_without_an_opening_one_drops_everything_before_it(
    endpoint_for: Any, key_file: Path
) -> None:
    llm = client(endpoint_for(ok({"content": "reasoning here</think>FINISH([2])"})), key_file)
    assert llm.complete([{"role": "user", "content": "q"}]) == "FINISH([2])"


def test_a_reasoning_only_reply_is_empty_text_so_the_agent_is_reminded(endpoint_for: Any, key_file: Path) -> None:
    reply = ok({"content": None, "reasoning_content": "thinking about FINISH([3])"})
    assert client(endpoint_for(reply), key_file).chat([], []) == Turn()


def test_tool_arguments_that_are_not_json_reach_the_agent_unchanged(endpoint_for: Any, key_file: Path) -> None:
    call = {"id": "c1", "type": "function", "function": {"name": "finish", "arguments": '{"answer": [1'}}
    turn = client(endpoint_for(ok({"content": None, "tool_calls": [call]})), key_file).chat([], [])
    assert turn.calls == (ToolCall("c1", "finish", '{"answer": [1'),)


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_a_busy_endpoint_is_retried_with_a_wait_and_the_run_goes_on(
    endpoint_for: Any, key_file: Path, status: int
) -> None:
    endpoint = endpoint_for((status, {"error": "busy"}, {}), (status, {"error": "busy"}, {}), ok({"content": "ok"}))
    sleeps: list[float] = []
    assert client(endpoint, key_file, sleeps).complete([{"role": "user", "content": "q"}]) == "ok"
    assert len(endpoint.requests) == 3 and len(sleeps) == 2 and all(s > 0 for s in sleeps)


def test_retry_after_is_honoured(endpoint_for: Any, key_file: Path) -> None:
    endpoint = endpoint_for((429, {}, {"Retry-After": "7"}), ok({"content": "ok"}))
    sleeps: list[float] = []
    client(endpoint, key_file, sleeps).complete([{"role": "user", "content": "q"}])
    assert sleeps == [7.0]


def test_an_endpoint_that_stays_busy_stops_the_run_with_a_clear_error(endpoint_for: Any, key_file: Path) -> None:
    endpoint = endpoint_for(*[(429, {"error": "slow down"}, {})] * 10)
    with pytest.raises(LlmError, match="429"):
        client(endpoint, key_file).complete([{"role": "user", "content": "q"}])
    assert len(endpoint.requests) == 5


def test_a_rejected_request_is_not_retried_and_never_shows_the_key(endpoint_for: Any, key_file: Path) -> None:
    endpoint = endpoint_for((401, {"error": "bad key"}, {}), ok({"content": "unreachable"}))
    with pytest.raises(LlmError, match="401") as error:
        client(endpoint, key_file).complete([{"role": "user", "content": "q"}])
    assert len(endpoint.requests) == 1 and "k3y" not in str(error.value)


def test_a_200_without_choices_is_an_error_not_a_silent_empty_reply(endpoint_for: Any, key_file: Path) -> None:
    endpoint = endpoint_for((200, {"error": {"message": "model overloaded"}}, {}))
    with pytest.raises(LlmError, match="model overloaded"):
        client(endpoint, key_file).complete([{"role": "user", "content": "q"}])


# --- the runner over HTTP --------------------------------------------------------------------------------------


def lookup_case() -> dict[str, Any]:
    """A benchmark task whose answer is in the task file, so grading needs no server."""
    return next(t for t in load_tasks() if t["id"].startswith("task1_") and t["sol"])


def finish_with(answer: list[Any]) -> tuple[int, Any, dict[str, str]]:
    call = {"id": "f", "type": "function", "function": {"name": "finish", "arguments": json.dumps({"answer": answer})}}
    return ok({"content": None, "tool_calls": [call]})


def test_arm_t_runs_a_task_over_http_into_a_graded_record(endpoint_for: Any, key_file: Path, tmp_path: Path) -> None:
    case = lookup_case()
    endpoint = endpoint_for(finish_with(case["sol"]))
    records = run_arm(
        "T",
        "nvidia/m",
        [case],
        load_functions(),
        lambda: client(endpoint, key_file),
        None,
        tmp_path / "T.jsonl",  # type: ignore[arg-type]
    )
    assert [(r["task_id"], r["status"], r["correct"]) for r in records] == [(case["id"], "completed", True)]


def test_arm_a_runs_a_task_over_http_into_a_graded_record(endpoint_for: Any, key_file: Path, tmp_path: Path) -> None:
    case = lookup_case()
    endpoint = endpoint_for(ok({"content": f"<think>done</think>FINISH({json.dumps(case['sol'])})"}))
    records = run_arm(
        "A",
        "nvidia/m",
        [case],
        load_functions(),
        lambda: client(endpoint, key_file),
        None,
        tmp_path / "A.jsonl",  # type: ignore[arg-type]
    )
    assert [(r["task_id"], r["status"], r["correct"]) for r in records] == [(case["id"], "completed", True)]


def test_a_run_that_dies_midway_resumes_without_repeating_finished_tasks(
    endpoint_for: Any, key_file: Path, tmp_path: Path
) -> None:
    first, second = [t for t in load_tasks() if t["id"].startswith("task1_") and t["sol"]][:2]
    out = tmp_path / "T.jsonl"
    dying = endpoint_for(finish_with(first["sol"]), *[(503, {}, {})] * 5)
    with pytest.raises(LlmError):
        run_arm("T", "m", [first, second], load_functions(), lambda: client(dying, key_file), None, out)  # type: ignore[arg-type]
    assert [json.loads(line)["task_id"] for line in out.read_text().splitlines()] == [first["id"]]
    resumed = endpoint_for(finish_with(second["sol"]))
    records = run_arm("T", "m", [first, second], load_functions(), lambda: client(resumed, key_file), None, out)  # type: ignore[arg-type]
    assert [r["task_id"] for r in records] == [first["id"], second["id"]] and len(resumed.requests) == 1
