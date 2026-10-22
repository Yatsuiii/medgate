"""The review screen end to end on the live FHIR server, with the demo ward and replay: the watch drafts cited orders,
nothing is written until one is approved, and an approved order reads back whole."""

import threading
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from medgate.fhir import FhirClient
from medgate.protocol import FHIR_BASE
from medgate.tasks import load_functions
from medgate.watch import load_ward
from medgate.web import ReviewApp, ReviewServer, load_replay

pytestmark = pytest.mark.live
FHIR = FhirClient()
if not FHIR.is_up():
    pytest.skip("FHIR server is not running on localhost:8080", allow_module_level=True)

DEMO = Path(__file__).resolve().parents[1] / "demo"
REPLAY = load_replay(DEMO / "replay.json")
WRITABLE = ("MedicationRequest", "ServiceRequest", "Observation")


def counts() -> dict[str, int]:
    """Live resource counts, bypassing the server's reuse of identical searches (see test_review_live.counts)."""
    fresh = {"Cache-Control": "no-cache"}
    url = "{}{}?_summary=count&_format=json"
    return {rt: int(httpx.get(url.format(FHIR_BASE, rt), headers=fresh).json()["total"]) for rt in WRITABLE}


@pytest.fixture
def site() -> Iterator[str]:
    mode = {"replay": True, "model": "", "ask": {"context": REPLAY.context, "question": REPLAY.question}}
    app = ReviewApp(REPLAY.llm_for, FHIR, load_functions(), mode, load_ward(DEMO / "ward.json"))
    server = ReviewServer(app, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_the_watch_worklist_drafts_cited_orders_only_where_the_protocol_calls_for_them(site: str) -> None:
    before = counts()
    events = httpx.post(f"{site}/api/watch", json={}, timeout=120).json()["events"]
    assert counts() == before  # watching wrote nothing
    assert len(events) == 12 and all(e["status"] == "completed" for e in events)
    drafted = {(e["patient"], e["result"]["code"]): len(e["proposals"]) for e in events if e["proposals"]}
    assert drafted == {("S6550627", "K"): 2, ("S3084624", "MG"): 1, ("S6542579", "MG"): 1}
    for event in events:
        for proposal in event["proposals"]:
            assert proposal["findings"] is None and proposal["evidence"][0]["id"] == event["result"]["id"]


def test_an_approved_watch_order_is_written_and_reads_back_whole(site: str) -> None:
    before = counts()
    events = httpx.post(f"{site}/api/watch", json={"patients": ["S3084624"]}, timeout=120).json()["events"]
    (magnesium,) = next(e for e in events if e["result"]["code"] == "MG")["proposals"]
    written = httpx.post(f"{site}/api/commit", json={"id": magnesium["id"]}, timeout=60).json()
    try:
        assert written["dropped"] == []
        stored = FHIR.read(written["reference"])
        assert stored["dosageInstruction"][0]["route"] == {"text": "IV"}
        assert counts()["MedicationRequest"] == before["MedicationRequest"] + 1
    finally:
        httpx.delete(f"{FHIR_BASE}{written['reference']}").raise_for_status()
    assert counts() == before


def test_the_ask_view_still_proposes_the_two_potassium_orders(site: str) -> None:
    result = httpx.post(f"{site}/api/ask", json={"context": REPLAY.context, "question": REPLAY.question}, timeout=60)
    medication, level = result.json()["proposals"]
    assert (medication["resource"], level["resource"]) == ("MedicationRequest", "ServiceRequest")
    assert medication["evidence"][0]["valueQuantity"]["value"] < 3.5
