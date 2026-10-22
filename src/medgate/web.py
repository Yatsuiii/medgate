"""The review screen: a local web page over the gated agent (arm TG), the results watch and the review step.

Two ways in. Ask: you put a question about a patient and the agent works on it. Watch: the agent takes each new
result the ward's protocols cover (medgate.watch) and drafts what the protocol calls for, so orders are waiting before
anyone has had to notice the result. Either way, the agent's steps and answer come back with every write it proposed,
each beside the records it cites and what the gates found. Nothing is written until a clinician approves a proposal;
an approved one is written as conformant FHIR and read back (medgate.review). For local use only: the server binds to
127.0.0.1 and has no authentication.

Replay mode runs scripted agent turns from a file (demo/), so the screen can be seen without a model; the page says so.
"""

import json
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, cast

import httpx

from medgate import review
from medgate.fhir import FhirClient
from medgate.gates import FULL, WATCH, GateConfig
from medgate.llm import ChatMessage, Llm, LlmError, ScriptedLlm, ToolCall, Turn
from medgate.review import Proposal
from medgate.tool_agent import run_tool_task
from medgate.watch import Event, Ward, case_for, new_results

PAGE = resources.files("medgate").joinpath("review_page.html")
# Agent runs a watch keeps in flight at once. One at a time, a ward of 12 results took 32 calls end to end; real
# endpoints rate-limit, and the model client waits out what they refuse, so a few in parallel is the safe middle.
WATCH_WORKERS = 4
# The agent configuration a watch scan uses: arm TG plus a one-time review of the agent's decision before it finishes.
# On held-out events it removed the silent misses (33 of 120 runs without an order became 0) without false orders
# (docs/HELDOUT_RESULTS.md). The ask view uses plain arm TG.
WATCH_CONFIG = WATCH


class UnknownProposal(Exception):
    pass


class NoWard(Exception):
    """The screen was started without a ward, so there is nothing to watch."""


class NoScript(Exception):
    """A replay has no scripted run for this task."""


def _turns(raw: list[dict[str, Any]]) -> tuple[Turn, ...]:
    return tuple(
        Turn(
            text=str(turn.get("text", "")),
            calls=tuple(ToolCall(str(c["id"]), str(c["name"]), str(c["arguments"])) for c in turn.get("calls", [])),
        )
        for turn in raw
    )


@dataclass(frozen=True)
class Replay:
    """Scripted agent runs for the screen, by task id: "ask" for the ask view, and one per watched result."""

    context: str  # what the ask view starts with
    question: str
    scripts: dict[str, tuple[Turn, ...]]

    def llm_for(self, case: dict[str, Any]) -> Llm:
        turns = self.scripts.get(str(case["id"]))
        if turns is None:
            raise NoScript(str(case["id"]))
        return ScriptedLlm(turns)


def load_replay(path: Path) -> Replay:
    data = cast(dict[str, Any], json.loads(path.read_text()))
    ask = cast(dict[str, Any], data["ask"])
    watched = cast(dict[str, list[dict[str, Any]]], data.get("watch", {}))
    scripts = {"ask": _turns(ask["turns"])} | {case_id: _turns(turns) for case_id, turns in watched.items()}
    return Replay(str(ask["context"]), str(ask["question"]), scripts)


def _parsed(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def steps(transcript: list[ChatMessage]) -> list[dict[str, Any]]:
    """The run as the page shows it: the model's notes, and each tool call with the first line of its result.

    Results are matched to calls by order, as they follow each reply; this holds even if a model repeats call ids.
    """
    shown: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []
    for message in transcript:
        if message["role"] == "assistant":
            if message.get("content"):
                shown.append({"note": message["content"]})
            for call in cast(list[dict[str, Any]], message.get("tool_calls") or []):
                function = cast(dict[str, Any], call["function"])
                step = {"tool": function["name"], "arguments": _parsed(str(function["arguments"])), "result": ""}
                shown.append(step)
                waiting.append(step)
        elif message["role"] == "tool" and waiting:
            waiting.pop(0)["result"] = str(message["content"]).split("\n", 1)[0][:300]
    return shown


class ReviewApp:
    """What the page can do, without HTTP: ask the gated agent, watch a ward's results, commit approved proposals."""

    def __init__(
        self,
        llm_for: Callable[[dict[str, Any]], Llm],
        fhir: FhirClient,
        functions: list[dict[str, Any]],
        mode: dict[str, Any],
        ward: Ward | None = None,
    ) -> None:
        self._llm_for = llm_for
        self._fhir = fhir
        self._functions = functions
        self._mode = mode  # {"replay": bool, "model": str, "ask": {"context": str, "question": str}}
        self.ward = ward
        self._proposals: dict[str, Proposal] = {}

    def describe(self) -> dict[str, Any]:
        """What the page shows about the agent and the ward."""
        ward = self.ward
        watched = None
        if ward is not None:
            protocols = [{"name": p.name, "code": p.code, "text": p.text} for p in ward.protocols]
            watched = {
                "now": ward.now,
                "window_hours": ward.window_hours,
                "patients": list(ward.patients),
                "protocols": protocols,
            }
        return {**self._mode, "ward": watched}

    def _card(self, proposal: Proposal) -> dict[str, Any]:
        proposal_id = uuid.uuid4().hex
        self._proposals[proposal_id] = proposal
        return {
            "id": proposal_id,
            "resource": proposal.resource,
            "payload": proposal.payload,
            "findings": proposal.findings,
            "superseded": proposal.superseded,
            "evidence": [_parsed(line) for line in proposal.evidence],
        }

    def _outcome(self, case: dict[str, Any], cfg: GateConfig = FULL) -> dict[str, Any]:
        """Run the gated agent on one task: its status, answer and steps, and every write it proposed as a card."""
        try:
            llm = self._llm_for(case)
        except NoScript:
            return {"status": "no scripted run in this replay", "answer": None, "steps": [], "proposals": []}
        try:
            result = run_tool_task(case, self._functions, llm, self._fhir, cfg)
        except LlmError as exc:  # the result stays on the worklist as unprocessed instead of taking the others down
            return {"status": f"model endpoint failed: {exc}", "answer": None, "steps": [], "proposals": []}
        cards = [self._card(p) for p in review.proposals(result.history, self._fhir)]
        answer = _parsed(result.result) if result.result is not None else None
        return {"status": result.status.value, "answer": answer, "steps": steps(result.transcript), "proposals": cards}

    def ask(self, context: str, question: str) -> dict[str, Any]:
        return self._outcome({"id": "ask", "context": context, "instruction": question})

    def watch(self, patients: list[str] | None = None) -> list[dict[str, Any]]:
        """One worklist entry per new result the ward's protocols cover, with what the agent drafted for it."""
        ward = self.ward
        if ward is None:
            raise NoWard()
        events = new_results(ward, self._fhir, patients)

        def outcome(event: Event) -> dict[str, Any]:
            return self._outcome(case_for(event, ward.now), WATCH_CONFIG)

        with ThreadPoolExecutor(WATCH_WORKERS) as pool:
            outcomes = list(pool.map(outcome, events))
        return [
            {"patient": event.patient, "protocol": event.protocol.name, "result": event.result, **outcome}
            for event, outcome in zip(events, outcomes, strict=True)
        ]

    def commit(self, proposal_id: str, override: bool = False) -> dict[str, Any]:
        if proposal_id not in self._proposals:
            raise UnknownProposal(proposal_id)
        committed = review.commit(self._proposals[proposal_id], self._fhir, override)
        return {"reference": committed.reference, "dropped": list(committed.dropped)}


def _ask(app: ReviewApp, body: dict[str, Any]) -> Any:
    return app.ask(str(body.get("context", "")), str(body.get("question", "")))


def _watch(app: ReviewApp, body: dict[str, Any]) -> Any:
    patients = body.get("patients")
    return {"events": app.watch([str(p) for p in cast(list[Any], patients)] if isinstance(patients, list) else None)}


def _commit(app: ReviewApp, body: dict[str, Any]) -> Any:
    return app.commit(str(body.get("id", "")), bool(body.get("override", False)))


_ACTIONS: dict[str, Callable[[ReviewApp, dict[str, Any]], Any]] = {
    "/api/ask": _ask,
    "/api/watch": _watch,
    "/api/commit": _commit,
}


class _Handler(BaseHTTPRequestHandler):
    def _send(self, status: HTTPStatus, body: str, content_type: str) -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: HTTPStatus, value: Any) -> None:
        self._send(status, json.dumps(value), "application/json")

    def do_GET(self) -> None:  # noqa: N802 - the name http.server dispatches to
        if self.path == "/":
            self._send(HTTPStatus.OK, PAGE.read_text(), "text/html; charset=utf-8")
        elif self.path == "/api/mode":
            self._json(HTTPStatus.OK, cast(ReviewServer, self.server).app.describe())
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - the name http.server dispatches to
        action = _ACTIONS.get(self.path)
        if action is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = None
        if not isinstance(body, dict):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "the body must be a JSON object"})
            return
        try:
            self._json(HTTPStatus.OK, action(cast(ReviewServer, self.server).app, cast(dict[str, Any], body)))
        except UnknownProposal:
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown proposal"})
        except NoWard:
            self._json(HTTPStatus.NOT_FOUND, {"error": "no ward is configured; start the screen with --ward"})
        except ValueError as exc:  # review.commit refusing a proposal the gates rejected
            self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
        except (httpx.HTTPError, RuntimeError) as exc:  # the FHIR server, or a watch search that failed
            self._json(HTTPStatus.BAD_GATEWAY, {"error": f"FHIR server: {exc}"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base class names it format
        pass


class ReviewServer(ThreadingHTTPServer):
    """The page and its actions over HTTP, on 127.0.0.1. Port 0 picks a free port."""

    def __init__(self, app: ReviewApp, port: int = 8765) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        self.app = app
