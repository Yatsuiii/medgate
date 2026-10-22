"""Run the watch on the held-out ward (docs/HELDOUT_PREREG.md) and judge each run against the oracle.

Usage, from the repository root with the FHIR server up and after `analysis/heldout.py build runs/heldout_ward.json`:
    uv run python -I analysis/heldout_run.py run --feature baseline --out runs/heldout_baseline.jsonl --repeats 5 \
        --model <MODEL> --base-url <URL> --key-file <FILE>
    uv run python -I analysis/heldout_run.py compare runs/heldout_baseline.jsonl runs/heldout_<treatment>.jsonl
The run is resumable. A feature is a named set of options for the watch's agent loop (FEATURES below).
"""

import argparse
import contextlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from medgate import review
from medgate.fhir import FhirClient
from medgate.gates import FULL, WATCH, GateConfig
from medgate.llm import Llm, OpenAiCompatibleLlm
from medgate.tasks import load_functions
from medgate.tool_agent import run_tool_task
from medgate.watch import Event, case_for, load_ward, new_results

FEATURES: dict[str, GateConfig] = {"baseline": FULL, "audit": WATCH}  # the agent configuration each arm runs with
MISSES_NEEDED = 6  # per 60 runs on the needs-orders events, below which the set does not reproduce the problem


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first(value: Any) -> dict[str, Any]:
    """The first element of a list as a dict, or {} for anything else: a malformed payload must not crash a check."""
    return _dict(value[0]) if isinstance(value, list) and value else {}


def _route(payload: dict[str, Any]) -> str:
    route = _first(payload.get("dosageInstruction")).get("route")
    return str(route.get("text") if isinstance(route, dict) else route or "").lower()


def _dose(payload: dict[str, Any]) -> dict[str, Any]:
    return _first(_first(payload.get("dosageInstruction")).get("doseAndRate"))


def _code(payload: dict[str, Any], field: str) -> str:
    return str(_first(_dict(payload.get(field)).get("coding")).get("code", ""))


def _quantity(dose: dict[str, Any], name: str) -> tuple[Any, Any]:
    quantity = _dict(dose.get(name))
    return quantity.get("value"), quantity.get("unit")


def _close(value: Any, want: float) -> bool:
    return isinstance(value, int | float) and abs(value - want) < 0.05


def magnesium_ok(payloads: list[dict[str, Any]], value: float) -> bool:
    """One magnesium order with the protocol's dose and duration for this level, IV."""
    grams = 1 if value >= 1.5 else 2 if value >= 1.0 else 4
    for p in payloads:
        dose = _dose(p)
        if (
            _code(p, "medicationCodeableConcept") == "0338-1715-40"
            and _route(p) == "iv"
            and _quantity(dose, "doseQuantity") == (grams, "g")
            and _quantity(dose, "rateQuantity") == (grams, "h")
        ):
            return True
    return False


def potassium_ok(payloads: list[dict[str, Any]], value: float, now: datetime) -> bool:
    """The oral potassium at the protocol's dose and the paired stat level drawn at 08:00 the next morning."""
    want = round((3.5 - value) / 0.1 * 10, 1)
    morning = (now + timedelta(days=1)).strftime("%Y-%m-%dT08:00")
    medication = any(
        _code(p, "medicationCodeableConcept") == "40032-917-01"
        and _route(p) == "oral"
        and _close(_quantity(_dose(p), "doseQuantity")[0], want)
        and _quantity(_dose(p), "doseQuantity")[1] == "mEq"
        for p in payloads
    )
    level = any(
        _code(p, "code") == "2823-3"
        and p.get("priority") == "stat"
        and str(p.get("occurrenceDateTime", "")).startswith(morning)
        for p in payloads
    )
    return medication and level


def judge(need: dict[str, Any], protocol: str, payloads: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Classify one run against the oracle: its kind, and whether the orders it drafted are accurate."""
    expected, drafted = int(need["orders"]), len(payloads)
    if expected == 0:
        kind = "false_order" if drafted else ("held_ok" if need.get("held") else "ok_none")
        return {"kind": kind, "payload_ok": None}
    if drafted == 0:
        return {"kind": "miss", "payload_ok": None}
    if drafted < expected:
        return {"kind": "incomplete", "payload_ok": None}
    ok = magnesium_ok(payloads, need["value"]) if protocol == "MG" else potassium_ok(payloads, need["value"], now)
    return {"kind": "complete", "payload_ok": ok}


def run_once(
    event: Event, need: dict[str, Any], repeat: int, feature: str, ward_now: str, llm: Llm, fhir: FhirClient
) -> dict[str, Any]:
    result = run_tool_task(case_for(event, ward_now), load_functions(), llm, fhir, FEATURES[feature])
    payloads = [p.payload for p in review.proposals(result.history, fhir)]
    calls = sum(m["role"] == "assistant" for m in result.transcript)
    return {
        "event": f"{event.patient}:{event.protocol.code}",
        "repeat": repeat,
        "feature": feature,
        "need": need,
        "orders": len(payloads),
        "model_calls": calls,
        "status": result.status.value,
        "format_retries": result.format_retries,
        **judge(need, event.protocol.code, payloads, datetime.fromisoformat(ward_now)),
        "transcript": result.transcript,
    }


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def run_all(
    feature: str, out: Path, repeats: int, quiet_repeats: int, workers: int, llm: Llm, fhir: FhirClient, ward_file: Path
) -> None:
    spec = json.loads(ward_file.read_text())
    ward = load_ward(ward_file)
    needs = {(e["patient"], e["protocol"]): e for e in spec["events"]}
    done = {(r["event"], r["repeat"]) for r in load_rows(out)}

    def runs_for(need: dict[str, Any]) -> int:
        return repeats if need["orders"] > 0 or need.get("held") else quiet_repeats

    jobs = [
        (e, needs[(e.patient, e.protocol.code)], k)
        for e in new_results(ward, fhir)
        if (e.patient, e.protocol.code) in needs
        for k in range(1, runs_for(needs[(e.patient, e.protocol.code)]) + 1)
        if (f"{e.patient}:{e.protocol.code}", k) not in done
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a") as sink, ThreadPoolExecutor(workers) as pool, contextlib.redirect_stdout(io.StringIO()):
        futures = [pool.submit(run_once, e, n, k, feature, ward.now, llm, fhir) for e, n, k in jobs]
        for future in futures:
            sink.write(json.dumps(future.result()) + "\n")
            sink.flush()


def totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    needs = [r for r in rows if r["need"]["orders"] > 0]
    complete = [r for r in needs if r["kind"] == "complete"]
    quiet = [r for r in rows if r["need"]["orders"] == 0]
    return {
        "runs": len(rows),
        "needs_orders_runs": len(needs),
        "misses": sum(r["kind"] == "miss" for r in needs),
        "incomplete": sum(r["kind"] == "incomplete" for r in needs),
        "complete": len(complete),
        "payload_ok": sum(bool(r["payload_ok"]) for r in complete),
        "quiet_runs": len(quiet),
        "false_orders": sum(r["kind"] == "false_order" for r in quiet),
        "model_calls": sum(r["model_calls"] for r in rows) / max(len(rows), 1),
    }


def describe(name: str, t: dict[str, Any]) -> str:
    acc = f"{t['payload_ok']}/{t['complete']}" if t["complete"] else "n/a"
    return (
        f"{name}: {t['runs']} runs. needs-orders {t['needs_orders_runs']}: misses {t['misses']}, incomplete "
        f"{t['incomplete']}, complete {t['complete']} (payload accurate {acc}). "
        f"need-nothing or hold {t['quiet_runs']}: false orders {t['false_orders']}. "
        f"model calls per run {t['model_calls']:.2f}"
    )


def verdict(base: dict[str, Any], treat: dict[str, Any]) -> str:
    """The pre-registered criteria of docs/HELDOUT_PREREG.md, applied to two runs' totals."""
    if base["misses"] * 60 < MISSES_NEEDED * base["needs_orders_runs"]:
        return "INCONCLUSIVE: the baseline has too few silent misses here (extend once if not already pooled)"
    acc = lambda t: t["payload_ok"] / t["complete"] if t["complete"] else 1.0  # noqa: E731
    fewer = treat["misses"] * 2 <= base["misses"]
    quiet_ok = treat["false_orders"] <= base["false_orders"] + 3
    accurate = acc(treat) >= acc(base) - 0.05
    not_worse = treat["incomplete"] <= base["incomplete"]
    if fewer and quiet_ok and accurate and not_worse:
        return "THE CHANGE WORKS by the pre-registered criteria"
    if treat["misses"] > 0.75 * base["misses"] or treat["false_orders"] >= base["false_orders"] + 8:
        return "THE CHANGE FAILS by the pre-registered criteria"
    return "CAUTION: no claim; look at the failures first"


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--feature", choices=sorted(FEATURES), required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--ward", type=Path, default=Path("runs/heldout_ward.json"))
    run.add_argument("--repeats", type=int, default=10, help="runs per event that needs orders or a hold")
    run.add_argument("--quiet-repeats", type=int, default=4, help="runs per event that needs nothing")
    run.add_argument("--workers", type=int, default=8)
    run.add_argument("--model", required=True)
    run.add_argument("--base-url", required=True)
    run.add_argument("--key-file", type=Path, default=Path.home() / ".nebius_key")
    compare = sub.add_parser("compare")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("treatment", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        model = OpenAiCompatibleLlm(
            args.base_url, args.model, key_file=args.key_file, temperature=1.0, top_p=0.95, max_tokens=8192
        )
        run_all(args.feature, args.out, args.repeats, args.quiet_repeats, args.workers, model, FhirClient(), args.ward)
        print(describe(args.feature, totals(load_rows(args.out))))
        return
    base, treat = totals(load_rows(args.baseline)), totals(load_rows(args.treatment))
    print(describe("baseline", base))
    print(describe("treatment", treat))
    print(f"verdict: {verdict(base, treat)}")


if __name__ == "__main__":
    main()
