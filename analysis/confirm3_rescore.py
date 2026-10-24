"""Rescore the third confirmation from saved transcripts, with no model call (docs/CONFIRM3_RESULTS.md, second table).

Each run's order list is rebuilt from its transcript with the same proposal logic bank_run.py uses. The rebuild is
validated first: with the original judge it must reproduce every saved `payload_ok`. The corrected judge differs from
the frozen one in exactly one place, named in PATCH below.

Usage, from the repository root with the FHIR server up:  uv run python -I analysis/confirm3_rescore.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE), str(HERE / "protocols")]

import bank_run  # noqa: E402
import p_clock_time_recheck as clock  # noqa: E402

from medgate import review  # noqa: E402
from medgate.fhir import FhirClient  # noqa: E402
from medgate.protocol import POST_ACCEPTED  # noqa: E402

NAMES = ["two_drugs_one_lab", "clock_time_recheck", "drug_plus_stat_lab"]
BASE = "http://localhost:8080/fhir/"
RESOURCE = {"medicationrequest_create": "MedicationRequest", "servicerequest_create": "ServiceRequest"}
NOW = datetime.fromisoformat("2023-11-13T10:15:00+00:00")
_FROZEN_ONCE = clock._once


def _patched_once(p: dict[str, Any]) -> bool:
    """PATCH: a dose with no timing at all is a single dose, as the watch's order tool says ("Leave it out for a
    single dose"). A repeat of 1 a day with no end is still not a single dose."""
    di = clock._first(p.get("dosageInstruction"))
    return not di.get("timing") and not di.get("text") or _FROZEN_ONCE(p)


def current_payloads(transcript: list[dict[str, Any]], fhir: FhirClient) -> list[dict[str, Any]]:
    calls: dict[str, tuple[str, Any]] = {}
    history: list[dict[str, str]] = []
    for m in transcript:
        for c in m.get("tool_calls") or []:
            calls[c["id"]] = (c["function"]["name"], c["function"]["arguments"])
        if m.get("role") == "tool" and m["tool_call_id"] in calls:
            name, raw = calls[m["tool_call_id"]]
            if name not in RESOURCE:
                continue
            try:
                args = json.loads(raw)
            except ValueError:
                continue
            payload = {"resourceType": RESOURCE[name], **args} if isinstance(args, dict) else None
            if payload is None:
                continue
            reply = POST_ACCEPTED if str(m["content"]).startswith("Accepted") else str(m["content"])
            history += [
                {"role": "agent", "content": f"POST {BASE}{RESOURCE[name]}\n{json.dumps(payload)}"},
                {"role": "user", "content": reply},
            ]
    props = review.proposals(history, fhir)  # type: ignore[arg-type]
    return [p.payload for p in props if p.findings is None and not p.superseded]


def main() -> None:
    fhir = FhirClient()
    mismatches = 0
    for name in NAMES:
        mod = bank_run.module(name)
        rows = [json.loads(line) for line in Path(f"runs/bank/{name}_confirm3_watch.jsonl").read_text().splitlines()]
        counts = {"frozen": 0, "patched": 0}
        n = 0
        for r in rows:
            payloads = current_payloads(r["transcript"], fhir)
            if len(payloads) != r["orders"]:
                mismatches += 1
            if r["kind"] != "complete":
                continue
            n += 1
            ok = bool(bank_run.judged(mod, r["need"], payloads, NOW)["payload_ok"])
            mismatches += ok != bool(r["payload_ok"])
            counts["frozen"] += ok
            if name == "clock_time_recheck":
                mod._once = _patched_once
            counts["patched"] += bool(bank_run.judged(mod, r["need"], payloads, NOW)["payload_ok"])
            mod._once = _FROZEN_ONCE if name == "clock_time_recheck" else getattr(mod, "_once", None)
        print(f"{name}: complete sets {n}: frozen judge accurate {counts['frozen']}, patched judge {counts['patched']}")
    print(f"replay mismatches against the saved rows: {mismatches}")


if __name__ == "__main__":
    main()
