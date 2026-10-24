"""Third-protocol test (docs/THIRD_PROTOCOL_PREREG.md): a calcium protocol the product was never tuned on.

Usage, from the repository root with the FHIR server up:
    uv run python -I analysis/third_protocol.py build runs/third_ward.json
    uv run python -I analysis/third_protocol.py run --out runs/third_agent.jsonl --model M --base-url U
    uv run python -I analysis/third_protocol.py script runs/third_ward.json
    uv run python -I analysis/third_protocol.py report runs/third_agent.jsonl
The oracle and the judge live here, in analysis code. The agent applies the protocol text and never sees them.
"""

import argparse
import contextlib
import io
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from heldout import SEED, newest  # noqa: E402
from heldout_run import _code, _dose, _quantity, _route, describe, load_rows, totals  # noqa: E402

from medgate import review  # noqa: E402
from medgate.fhir import FhirClient  # noqa: E402
from medgate.gates import WATCH  # noqa: E402
from medgate.llm import Llm, OpenAiCompatibleLlm  # noqa: E402
from medgate.protocol import FHIR_BASE  # noqa: E402
from medgate.tasks import load_functions  # noqa: E402
from medgate.tool_agent import run_tool_task  # noqa: E402
from medgate.watch import Event, case_for, load_ward, new_results  # noqa: E402

PROTOCOL = {
    "name": "Calcium replacement",
    "code": "CA",
    "text": (
        "Calcium replacement protocol (serum calcium, code CA, drawn in the last 24 hours). If the newest calcium is "
        "below 8.5 mg/dL, order IV calcium gluconate, NDC 63323-0300-10, route IV: 8.0 to below 8.5 mg/dL, 1 g over "
        "1 hour; below 8.0 mg/dL, 2 g over 2 hours. Record the dose in g and the duration as a rate in hours. Pair "
        "that order with a repeat serum calcium level, LOINC 17861-6, priority routine, to be drawn 6 hours after the "
        "order is written. If the calcium is 8.5 or higher, order nothing. Exclusion: before ordering, check the "
        "newest albumin (code ALB). If it is below 3.5 g/dL, the low calcium may reflect low albumin: do not order, "
        "hold it for pharmacist review."
    ),
}
NORMAL_KEPT = 14


def need_for(calcium: float, albumin: float) -> dict[str, Any]:
    low = calcium < 8.5
    held = low and albumin < 3.5
    return {"orders": 2 if low and not held else 0, "value": calcium, "held": held}


def build(out: Path) -> None:
    demo = json.loads(Path("demo/ward.json").read_text())
    now, window = datetime.fromisoformat(demo["now"]), timedelta(hours=float(demo["window_hours"]))
    fhir = FhirClient()
    entries = json.loads(str(fhir.get(f"{FHIR_BASE}Patient?_count=1000&_elements=id&_format=json").data))["entry"]
    mrns = sorted(e["resource"]["id"] for e in entries)
    with ThreadPoolExecutor(8) as pool:
        scans = list(pool.map(lambda m: (m, newest(fhir, m, "CA", now), newest(fhir, m, "ALB", now)), mrns))
    fresh = [(m, c, a) for m, c, a in scans if c is not None and c[1] >= now - window and a is not None]
    events = [{"patient": m, "protocol": "CA", **need_for(c[0], a[0])} for m, c, a in fresh]
    acting = [e for e in events if e["orders"] > 0 or e["held"]]
    quiet = [e for e in events if e not in acting]
    chosen = acting + random.Random(SEED).sample(quiet, min(NORMAL_KEPT, len(quiet)))
    ward = {
        "now": demo["now"],
        "window_hours": demo["window_hours"],
        "protocols": [PROTOCOL],
        "patients": [e["patient"] for e in chosen],
        "events": chosen,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ward, indent=1) + "\n")
    print(
        f"{len(fresh)} patients with a fresh CA and an albumin; kept {len(chosen)}: "
        f"{sum(e['orders'] > 0 for e in chosen)} need orders, {sum(e['held'] for e in chosen)} held, "
        f"{sum(e['orders'] == 0 and not e['held'] for e in chosen)} need nothing"
    )


def calcium_ok(payloads: list[dict[str, Any]], value: float, now: datetime) -> bool:
    """The calcium order at the protocol's dose and duration for this level, and the level drawn 6 hours later."""
    grams = 1 if value >= 8.0 else 2
    due = (now + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M")
    medication = any(
        _code(p, "medicationCodeableConcept") == "63323-0300-10"
        and _route(p) == "iv"
        and _quantity(_dose(p), "doseQuantity") == (grams, "g")
        and _quantity(_dose(p), "rateQuantity") == (grams, "h")
        for p in payloads
    )
    level = any(
        _code(p, "code") == "17861-6"
        and p.get("priority") == "routine"
        and str(p.get("occurrenceDateTime", "")).startswith(due)
        for p in payloads
    )
    return medication and level


def judge(need: dict[str, Any], payloads: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    expected, drafted = int(need["orders"]), len(payloads)
    if expected == 0:
        return {"kind": "false_order" if drafted else ("held_ok" if need["held"] else "ok_none"), "payload_ok": None}
    if drafted == 0:
        return {"kind": "miss", "payload_ok": None}
    if drafted < expected:
        return {"kind": "incomplete", "payload_ok": None}
    return {"kind": "complete", "payload_ok": calcium_ok(payloads, need["value"], now)}


def run_once(
    event: Event, need: dict[str, Any], repeat: int, ward_now: str, llm: Llm, fhir: FhirClient
) -> dict[str, Any]:
    result = run_tool_task(case_for(event, ward_now), load_functions(), llm, fhir, WATCH)
    payloads = [p.payload for p in review.proposals(result.history, fhir)]
    return {
        "event": f"{event.patient}:CA",
        "repeat": repeat,
        "need": need,
        "orders": len(payloads),
        "model_calls": sum(m["role"] == "assistant" for m in result.transcript),
        "status": result.status.value,
        "format_retries": result.format_retries,
        **judge(need, payloads, datetime.fromisoformat(ward_now)),
        "transcript": result.transcript,
    }


def run_all(out: Path, ward_file: Path, workers: int, llm: Llm, fhir: FhirClient) -> None:
    spec = json.loads(ward_file.read_text())
    ward = load_ward(ward_file)
    needs = {e["patient"]: e for e in spec["events"]}
    done = {(r["event"], r["repeat"]) for r in load_rows(out)}

    def runs_for(need: dict[str, Any]) -> int:
        return 10 if need["orders"] > 0 else 5 if need["held"] else 4

    jobs = [
        (e, needs[e.patient], k)
        for e in new_results(ward, fhir)
        if e.patient in needs
        for k in range(1, runs_for(needs[e.patient]) + 1)
        if (f"{e.patient}:CA", k) not in done
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a") as sink, ThreadPoolExecutor(workers) as pool, contextlib.redirect_stdout(io.StringIO()):
        futures = [pool.submit(run_once, e, n, k, ward.now, llm, fhir) for e, n, k in jobs]
        for future in futures:
            sink.write(json.dumps(future.result()) + "\n")
            sink.flush()


# --- the hand-coded rule script for this protocol (the baseline) ---
def rule_script(calcium: float, albumin: float, obs: str, mrn: str, now: datetime) -> list[dict[str, Any]]:
    if calcium >= 8.5 or albumin < 3.5:
        return []
    g = 1 if calcium >= 8.0 else 2
    ref = [{"reference": f"Observation/{obs}"}]
    dose = {"doseQuantity": {"value": g, "unit": "g"}, "rateQuantity": {"value": g, "unit": "h"}}
    return [
        {
            "medicationCodeableConcept": {"coding": [{"code": "63323-0300-10"}]},
            "dosageInstruction": [{"route": "IV", "doseAndRate": [dose]}],
            "subject": {"reference": mrn},
            "reasonReference": ref,
        },
        {
            "code": {"coding": [{"code": "17861-6"}]},
            "priority": "routine",
            "occurrenceDateTime": (now + timedelta(hours=6)).isoformat(timespec="seconds"),
            "subject": {"reference": mrn},
            "reasonReference": ref,
        },
    ]


def script_rows(ward_file: Path) -> list[dict[str, Any]]:
    spec = json.loads(ward_file.read_text())
    now, fhir = datetime.fromisoformat(spec["now"]), FhirClient()
    rows: list[dict[str, Any]] = []
    for need in spec["events"]:
        calcium, albumin = newest(fhir, need["patient"], "CA", now), newest(fhir, need["patient"], "ALB", now)
        assert calcium is not None and albumin is not None
        found = json.loads(
            str(fhir.get(f"{FHIR_BASE}Observation?patient={need['patient']}&code=CA&_count=5000&_format=json").data)
        )
        ids = {
            clinical: r["id"]
            for r in (e["resource"] for e in found["entry"])
            if (clinical := r.get("effectiveDateTime"))
        }
        obs = next(iter(ids.values()), "")
        payloads = rule_script(calcium[0], albumin[0], obs, need["patient"], now)
        rows.append(
            {
                "event": need["patient"],
                "need": need,
                "model_calls": 0,
                "orders": len(payloads),
                **judge(need, payloads, now),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build").add_argument("out", type=Path)
    run = sub.add_parser("run")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--ward", type=Path, default=Path("runs/third_ward.json"))
    run.add_argument("--workers", type=int, default=8)
    run.add_argument("--model", required=True)
    run.add_argument("--base-url", required=True)
    run.add_argument("--key-file", type=Path, default=Path.home() / ".nebius_key")
    sub.add_parser("script").add_argument("ward", type=Path)
    sub.add_parser("report").add_argument("rows", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        build(args.out)
    elif args.command == "run":
        llm = OpenAiCompatibleLlm(
            args.base_url, args.model, key_file=args.key_file, temperature=1.0, top_p=0.95, max_tokens=8192
        )
        run_all(args.out, args.ward, args.workers, llm, FhirClient())
        print(describe("agent", totals(load_rows(args.out))))
    elif args.command == "script":
        print(describe("script", totals(script_rows(args.ward))))
    else:
        print(describe("agent", totals(load_rows(args.rows))))


if __name__ == "__main__":
    main()
