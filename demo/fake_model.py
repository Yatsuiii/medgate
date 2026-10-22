"""A fake OpenAI-compatible model endpoint that replays demo/replay.json's scripted runs over HTTP.

For trying the review screen's live mode without a key: `medgate serve` talks to this endpoint exactly as it would to
Nebius Token Factory or the NVIDIA API, so the model client, the tool-call wire format, concurrent runs and waiting
times are all exercised. Every reply is scripted, so nothing it produces is model output. Its model name shows on the
page; never record a demo against it.

Usage, from the repository root (any non-empty key file works):
    uv run python -I demo/fake_model.py --port 8787 --latency 2
    uv run medgate serve --ward demo/ward.json --model scripted-fake-endpoint \
        --base-url http://127.0.0.1:8787/v1 --key-file <file>
"""

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

REPLAY = Path(__file__).resolve().parent / "replay.json"
WATCH_QUESTION = re.compile(r"New result for patient (\S+): (\S+) ")


class FakeModel(ThreadingHTTPServer):
    """Answers each chat completion with the next scripted turn of the run its first user message belongs to.

    `latency` seconds pass before every reply, standing in for a real model's thinking time. Requests for a patient in
    `failing` get HTTP 401, as a misconfigured endpoint would answer. `max_in_flight` records the most requests that
    were being answered at once.
    """

    def __init__(self, port: int = 0, latency: float = 0.0, failing: frozenset[str] = frozenset()) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        replay = cast(dict[str, Any], json.loads(REPLAY.read_text()))
        self.scripts: dict[str, list[dict[str, Any]]] = {"ask": replay["ask"]["turns"], **replay["watch"]}
        self.ask_question = str(replay["ask"]["question"])
        self.latency = latency
        self.failing = failing
        self.max_in_flight = 0
        self._in_flight = 0
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/v1"

    def script_for(self, question: str) -> str | None:
        """The replay key of the run this question starts, or None when the replay has no such run."""
        if match := WATCH_QUESTION.search(question):
            return f"watch:{match[1]}:{match[2]}"
        return "ask" if self.ask_question in question else None

    def reply(self, messages: list[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        question = next((str(m["content"]) for m in messages if m["role"] == "user"), "")
        key = self.script_for(question)
        if key is not None and key.startswith("watch:") and key.split(":")[1] in self.failing:
            return 401, {"error": {"message": "invalid API key"}}
        turns = self.scripts.get(key or "")
        done = sum(1 for m in messages if m["role"] == "assistant")
        if turns is None or done >= len(turns):
            return 400, {"error": {"message": f"no scripted turn {done} for this conversation"}}
        turn = turns[done]
        calls = [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
            for c in turn["calls"]
        ]
        message: dict[str, Any] = {"role": "assistant", "content": turn["text"] or None}
        if calls:
            message["tool_calls"] = calls
        return 200, {"choices": [{"message": message, "finish_reason": "tool_calls" if calls else "stop"}]}

    def answer(self, messages: list[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            time.sleep(self.latency)
            return self.reply(messages)
        finally:
            with self._lock:
                self._in_flight -= 1


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - the name http.server dispatches on
        body = cast(dict[str, Any], json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        status, payload = cast(FakeModel, self.server).answer(cast(list[dict[str, Any]], body["messages"]))
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base class names it format
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--latency", type=float, default=2.0, help="seconds before each reply")
    args = parser.parse_args()
    server = FakeModel(args.port, args.latency)
    print(f"scripted fake model endpoint: {server.url} (latency {args.latency} s)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
