"""The review screen over real HTTP, with scripted agents and a fake FHIR store. No FHIR server needed."""

import json
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from medgate import web
from medgate.cli import main
from medgate.fhir import GetResult
from medgate.gates import FULL
from medgate.llm import ScriptedLlm, ToolCall, Turn
from medgate.watch import Protocol, Ward
from medgate.web import NoScript, ReviewApp, ReviewServer, load_replay, steps

REPLAY = Path(__file__).resolve().parents[1] / "demo" / "replay.json"
BASE = "http://localhost:8080/fhir/"
NOW = "2023-11-13T10:15:00+00:00"
FUNCS: list[dict[str, Any]] = [
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
    }
]
GOOD = {"status": "active", "subject": {"reference": "Patient/S100"}}
BAD = {"subject": {"reference": "Patient/S100"}}  # no status: the payload gate rejects it
POTASSIUM = Protocol("Potassium replacement", "K", "If potassium is below 3.5, order a recheck.")


def observation(id_: str, patient: str, value: float) -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "id": id_,
        "code": {"coding": [{"system": "http://loinc.org", "code": "K", "display": "K"}], "text": "K"},
        "subject": {"reference": f"Patient/{patient}"},
        "effectiveDateTime": "2023-11-13T06:00:00+00:00",
        "valueQuantity": {"value": value, "unit": "mmol/L"},
    }


RESULTS = {"S1": observation("k1", "S1", 3.1), "S2": observation("k2", "S2", 4.2), "S4": observation("k4", "S4", 3.0)}


class FakeFhir:
    """Potassium searches and reads from RESULTS, and a store for writes."""

    base = BASE

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    def get(self, url: str) -> GetResult:
        if match := re.search(r"Observation\?patient=(\w+)&code=K", url):
            rows = [RESULTS[match.group(1)]] if match.group(1) in RESULTS else []
            return GetResult(data=json.dumps({"resourceType": "Bundle", "entry": [{"resource": r} for r in rows]}))
        if match := re.search(r"Observation/(\w+)\?", url):
            found = [r for r in RESULTS.values() if r["id"] == match.group(1)]
            return GetResult(data=json.dumps(found[0])) if found else GetResult(error="404 Not Found")
        return GetResult(error="404 Not Found")

    def create(self, resource_type: str, payload: dict[str, Any]) -> str:
        self.created.append(payload)
        return f"{resource_type}/{len(self.created)}"

    def read(self, reference: str) -> dict[str, Any]:
        return self.created[int(reference.split("/")[1]) - 1]


def finish(answer: list[Any]) -> Turn:
    return Turn(calls=(ToolCall("f", "finish", json.dumps({"answer": answer})),))


def ask_turns() -> list[Turn]:
    writes = [
        ToolCall("a", "servicerequest_create", json.dumps(BAD)),
        ToolCall("b", "servicerequest_create", json.dumps(GOOD)),
    ]
    return [Turn(text="Plan: order the test.", calls=tuple(writes)), finish([])]


def recheck(patient: str, observation_id: str) -> Turn:
    order = {
        "status": "active",
        "subject": {"reference": f"Patient/{patient}"},
        "reasonReference": [{"reference": f"Observation/{observation_id}"}],
    }
    return Turn(calls=(ToolCall("o", "servicerequest_create", json.dumps(order)),))


SCRIPTS = {
    "ask": ask_turns,
    "watch:S1:K": lambda: [recheck("S1", "k1"), finish([3.1]), finish([3.1])],  # the second answers the review
    "watch:S2:K": lambda: [finish([4.2]), finish([4.2])],
}


def llm_for(case: dict[str, Any]) -> ScriptedLlm:
    if case["id"] not in SCRIPTS:
        raise NoScript(case["id"])
    return ScriptedLlm(SCRIPTS[case["id"]]())


def serve(ward: Ward | None) -> tuple[ReviewServer, FakeFhir]:
    fhir = FakeFhir()
    mode = {"replay": True, "model": "", "ask": {"context": "C", "question": "Order a test for patient S100"}}
    server = ReviewServer(ReviewApp(llm_for, fhir, FUNCS, mode, ward), 0)  # type: ignore[arg-type]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, fhir


@pytest.fixture
def site() -> Iterator[tuple[str, FakeFhir]]:
    server, fhir = serve(Ward(NOW, 24, ("S1", "S2", "S3"), (POTASSIUM,)))
    yield f"http://127.0.0.1:{server.server_port}", fhir
    server.shutdown()
    server.server_close()


@pytest.fixture
def unwatched_site() -> Iterator[str]:
    server, _ = serve(None)
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def ask(url: str) -> dict[str, Any]:
    response = httpx.post(f"{url}/api/ask", json={"context": "C", "question": "Order a test for patient S100"})
    assert response.status_code == 200
    return response.json()


def test_the_page_is_self_contained_and_has_both_views(site: tuple[str, FakeFhir]) -> None:
    page = httpx.get(f"{site[0]}/")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    parts = [
        'id="scan"',
        'id="worklist"',
        'id="question"',
        'id="run"',
        'id="proposals"',
        "Approve and write",
        "Replay:",
    ]
    assert all(part in page.text for part in parts)
    assert not re.search(r"<(script|link|img)[^>]+(src|href)=", page.text)  # nothing loaded from elsewhere


def test_mode_describes_the_agent_and_the_ward(site: tuple[str, FakeFhir], unwatched_site: str) -> None:
    mode = httpx.get(f"{site[0]}/api/mode").json()
    assert mode["replay"] is True and mode["ask"]["question"].startswith("Order a test")
    assert mode["ward"]["patients"] == ["S1", "S2", "S3"] and mode["ward"]["protocols"][0]["code"] == "K"
    assert httpx.get(f"{unwatched_site}/api/mode").json()["ward"] is None


def test_ask_returns_steps_answer_and_every_proposed_write(site: tuple[str, FakeFhir]) -> None:
    result = ask(site[0])
    assert result["status"] == "completed" and result["answer"] == []
    assert result["steps"][0] == {"note": "Plan: order the test."}
    assert [s["tool"] for s in result["steps"][1:]] == ["servicerequest_create", "servicerequest_create", "finish"]
    rejected, accepted = result["proposals"]
    assert "'status' is missing" in rejected["findings"] and accepted["findings"] is None
    assert site[1].created == []  # asking proposes; it never writes
    assert result["steps"][2]["result"] == "Accepted: the write is recorded."  # never "created" before review


def test_watch_lists_every_new_result_with_what_the_agent_drafted(site: tuple[str, FakeFhir]) -> None:
    events = httpx.post(f"{site[0]}/api/watch", json={}).json()["events"]
    assert [(e["patient"], e["result"]["id"], e["status"]) for e in events] == [
        ("S1", "k1", "completed"),
        ("S2", "k2", "completed"),
    ]  # S3 has no potassium result, so it is not on the worklist
    (order,) = events[0]["proposals"]
    assert order["findings"] is None and order["evidence"][0]["valueQuantity"]["value"] == 3.1
    assert events[1]["proposals"] == [] and events[1]["answer"] == [4.2]
    assert site[1].created == []


def test_watch_takes_the_patients_from_the_page_and_says_when_a_replay_has_no_run(site: tuple[str, FakeFhir]) -> None:
    events = httpx.post(f"{site[0]}/api/watch", json={"patients": ["S4"]}).json()["events"]
    assert [(e["patient"], e["status"], e["proposals"]) for e in events] == [
        ("S4", "no scripted run in this replay", [])
    ]


def test_watch_without_a_ward_is_refused_plainly(unwatched_site: str) -> None:
    response = httpx.post(f"{unwatched_site}/api/watch", json={})
    assert response.status_code == 404 and "--ward" in response.json()["error"]


def test_commit_writes_an_approved_proposal_and_refuses_a_rejected_one(site: tuple[str, FakeFhir]) -> None:
    url, fhir = site
    rejected, accepted = ask(url)["proposals"]
    written = httpx.post(f"{url}/api/commit", json={"id": accepted["id"]})
    assert written.status_code == 200 and written.json() == {"reference": "ServiceRequest/1", "dropped": []}
    refused = httpx.post(f"{url}/api/commit", json={"id": rejected["id"]})
    assert refused.status_code == 409 and "the gates rejected this write" in refused.json()["error"]
    assert len(fhir.created) == 1
    overridden = httpx.post(f"{url}/api/commit", json={"id": rejected["id"], "override": True})
    assert overridden.status_code == 200 and len(fhir.created) == 2


@pytest.mark.parametrize(
    ("path", "body", "status"),
    [("/api/commit", {"id": "nope"}, 404), ("/api/nothing", {}, 404), ("/api/ask", "not json", 400)],
)
def test_bad_requests_get_plain_errors(site: tuple[str, FakeFhir], path: str, body: Any, status: int) -> None:
    content = body if isinstance(body, str) else json.dumps(body)
    assert httpx.post(f"{site[0]}{path}", content=content).status_code == status


def test_steps_pair_results_with_calls_in_order_even_when_ids_repeat() -> None:
    calls = [
        {"id": "x", "type": "function", "function": {"name": "calculator", "arguments": '{"expression": "1+1"}'}},
        {"id": "x", "type": "function", "function": {"name": "calculator", "arguments": '{"expression": "2+2"}'}},
    ]
    transcript = [
        {"role": "assistant", "content": None, "tool_calls": calls},
        {"role": "tool", "tool_call_id": "x", "content": "2"},
        {"role": "tool", "tool_call_id": "x", "content": "4\nmore"},
    ]
    assert [s["result"] for s in steps(transcript)] == ["2", "4"]


def test_the_demo_replay_has_the_ask_run_and_one_run_per_watched_result() -> None:
    replay = load_replay(REPLAY)
    names = [call.name for turn in replay.scripts["ask"] for call in turn.calls]
    assert names == [
        "observation_search_labs",
        "calculator",
        "medicationrequest_create",
        "servicerequest_create",
        "finish",
    ]
    assert "potassium" in replay.question and replay.scripts["ask"][0].text.startswith("Scripted replay")
    assert len([key for key in replay.scripts if key.startswith("watch:")]) == 12


def test_serve_refuses_to_start_without_a_model_or_a_replay(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["serve", "--key-file", str(tmp_path / "missing")]) == 2
    assert "--replay FILE" in capsys.readouterr().err


def test_the_watch_gets_the_finish_review_and_the_ask_view_does_not(
    site: tuple[str, FakeFhir], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ask script has one finish and completes, so the ask view runs without the review. A watch run is answered
    with the review at its first finish and completes at its second; with plain arm TG it completes at the first."""
    assert ask(site[0])["status"] == "completed"
    assert web.WATCH_CONFIG.finish_review is True
    events = httpx.post(f"{site[0]}/api/watch", json={"patients": ["S2"]}).json()["events"]
    assert events[0]["status"] == "completed" and events[0]["answer"] == [4.2]
    assert [st["result"][:17] for st in events[0]["steps"]] == ["Before you finish", "Finished."]
    monkeypatch.setattr(web, "WATCH_CONFIG", FULL)
    events = httpx.post(f"{site[0]}/api/watch", json={"patients": ["S2"]}).json()["events"]
    assert [st["result"] for st in events[0]["steps"]] == ["Finished."]
