"""The review screen in live mode: a model endpoint behind it over real HTTP, as on Nebius or the NVIDIA API.

The endpoint is demo/fake_model.py, which replays the demo's scripted runs, so the outcome must match replay mode
exactly. What this adds over replay mode: the model client on the wire, watch runs in parallel, and a failing endpoint.
"""

import importlib.util
import threading
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

from medgate.fhir import FhirClient
from medgate.llm import OpenAiCompatibleLlm
from medgate.tasks import load_functions
from medgate.watch import load_ward
from medgate.web import ReviewApp, ReviewServer, load_replay

pytestmark = pytest.mark.live
FHIR = FhirClient()
if not FHIR.is_up():
    pytest.skip("FHIR server is not running on localhost:8080", allow_module_level=True)

DEMO = Path(__file__).resolve().parents[1] / "demo"
REPLAY = load_replay(DEMO / "replay.json")
DRAFTED_IN_REPLAY = {("S6550627", "K"): 2, ("S3084624", "MG"): 1, ("S6542579", "MG"): 1}


def fake_model_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fake_model", DEMO / "fake_model.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FAKE_MODEL = fake_model_module()


@pytest.fixture
def live_site(tmp_path: Path) -> Iterator[Any]:
    """Start the fake endpoint and the screen on it; yields a function taking the patients the endpoint fails for."""
    started: list[Any] = []

    def start(failing: frozenset[str] = frozenset()) -> tuple[str, Any]:
        model = FAKE_MODEL.FakeModel(0, 0.2, failing)
        threading.Thread(target=model.serve_forever, daemon=True).start()
        key = tmp_path / "key"
        key.write_text("not-a-real-key\n")
        llm = OpenAiCompatibleLlm(model.url, "scripted-fake-endpoint", key_file=key, sleep=lambda _: None)
        mode = {"replay": False, "model": "scripted-fake-endpoint", "ask": {"context": "", "question": ""}}
        app = ReviewApp(lambda case: llm, FHIR, load_functions(), mode, load_ward(DEMO / "ward.json"))
        server = ReviewServer(app, 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        started.extend([model, server])
        return f"http://127.0.0.1:{server.server_port}", model

    yield start
    for server in started:
        server.shutdown()
        server.server_close()


def drafted(events: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    return {(e["patient"], e["result"]["code"]): len(e["proposals"]) for e in events if e["proposals"]}


def test_live_mode_drafts_the_replay_orders_with_runs_in_parallel(live_site: Any) -> None:
    site, model = live_site()
    events = httpx.post(f"{site}/api/watch", json={}, timeout=120).json()["events"]
    assert len(events) == 12 and all(e["status"] == "completed" for e in events)
    assert drafted(events) == DRAFTED_IN_REPLAY
    assert model.max_in_flight > 1  # runs overlapped instead of queueing behind each other


def test_a_failing_model_endpoint_marks_only_its_results_unprocessed(live_site: Any) -> None:
    site, _ = live_site(frozenset({"S3084624"}))
    events = httpx.post(f"{site}/api/watch", json={}, timeout=120).json()["events"]
    failed = {e["result"]["code"]: e["status"] for e in events if e["patient"] == "S3084624"}
    assert set(failed) == {"K", "MG"}
    assert all(status.startswith("model endpoint failed: HTTP 401") for status in failed.values())
    others = [e for e in events if e["patient"] != "S3084624"]
    assert len(others) == 10 and all(e["status"] == "completed" for e in others)
    assert drafted(events) == {k: v for k, v in DRAFTED_IN_REPLAY.items() if k[0] != "S3084624"}


def test_the_ask_view_works_in_live_mode(live_site: Any) -> None:
    site, _ = live_site()
    body = {"context": REPLAY.context, "question": REPLAY.question}
    outcome = httpx.post(f"{site}/api/ask", json=body, timeout=60).json()
    assert outcome["status"] == "completed" and len(outcome["proposals"]) == 2
