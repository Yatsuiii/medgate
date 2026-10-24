"""Run the watch on a protocol of the bank (analysis/protocols/p_<name>.py), judged by that module's oracle.

Usage, from the repository root with the FHIR server up:
    uv run python -I analysis/bank_run.py ward NAME            # build runs/bank/NAME_ward.json
    uv run python -I analysis/bank_run.py run NAME --config watch --out FILE --model M --base-url U
    uv run python -I analysis/bank_run.py script NAME          # the hand-coded rule script on the same events
    uv run python -I analysis/bank_run.py report FILE...       # totals of finished runs
A config is a named set of agent options (CONFIGS below). The oracle and the judge never reach the agent.
"""

import argparse
import contextlib
import importlib
import io
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE), str(HERE / "protocols")]

from heldout_run import describe, load_rows, totals  # noqa: E402

from medgate import review  # noqa: E402
from medgate.fhir import FhirClient  # noqa: E402
from medgate.gates import WATCH, WATCH_CHECKED, GateConfig  # noqa: E402
from medgate.llm import Llm, OpenAiCompatibleLlm  # noqa: E402
from medgate.protocol import FHIR_BASE  # noqa: E402
from medgate.tasks import watch_functions  # noqa: E402
from medgate.tool_agent import run_tool_task  # noqa: E402
from medgate.watch import Event, case_for, load_ward, new_results  # noqa: E402

CONFIGS: dict[str, GateConfig] = {"watch": WATCH, "checked": WATCH_CHECKED}
OUT = Path("runs/bank")
NORMAL_KEPT = 12
REPEATS = {"orders": 8, "held": 4, "none": 3}


def module(name: str) -> Any:
    return importlib.import_module(f"p_{name}")


def kind_of(need: dict[str, Any]) -> str:
    return "orders" if need["orders"] > 0 else "held" if need.get("held") else "none"


def ward_path(name: str) -> Path:
    return OUT / f"{name}_ward.json"


def build(name: str) -> None:
    mod = module(name)
    demo = json.loads(Path("demo/ward.json").read_text())
    now, window = datetime.fromisoformat(demo["now"]), timedelta(hours=float(demo["window_hours"]))
    fhir = FhirClient()
    entries = json.loads(str(fhir.get(f"{FHIR_BASE}Patient?_count=1000&_elements=id&_format=json").data))["entry"]
    mrns = sorted(e["resource"]["id"] for e in entries)
    with ThreadPoolExecutor(8) as pool:
        scans = list(pool.map(lambda m: (m, mod.needs(fhir, m, now, window)), mrns))
    events = [{"patient": m, "protocol": mod.PROTOCOL["code"], **n} for m, n in scans if n is not None]
    acting = [e for e in events if kind_of(e) != "none"]
    quiet = [e for e in events if kind_of(e) == "none"]
    chosen = acting + random.Random(0).sample(quiet, min(NORMAL_KEPT, len(quiet)))
    spec = {
        "now": demo["now"],
        "window_hours": demo["window_hours"],
        "protocols": [{k: mod.PROTOCOL[k] for k in ("name", "code", "text")}],
        "patients": [e["patient"] for e in chosen],
        "events": chosen,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    ward_path(name).write_text(json.dumps(spec, indent=1) + "\n")
    count = lambda k: sum(kind_of(e) == k for e in chosen)  # noqa: E731
    print(
        f"{name}: kept {len(chosen)} events: {count('orders')} need orders, {count('held')} held, {count('none')} none"
    )


def wrong_patient(need: dict[str, Any], payloads: list[dict[str, Any]]) -> bool:
    """Any drafted order whose subject is not the event's patient (the modules' judges cannot see the patient)."""

    def subject(p: dict[str, Any]) -> str:
        ref = p.get("subject")
        return str(ref.get("reference", "") if isinstance(ref, dict) else "").removeprefix("Patient/")

    return any(subject(p) != need["patient"] for p in payloads)


def judged(mod: Any, need: dict[str, Any], payloads: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    expected, drafted = int(need["orders"]), len(payloads)
    if expected == 0:
        return {
            "kind": "false_order" if drafted else ("held_ok" if need.get("held") else "ok_none"),
            "payload_ok": None,
        }
    if drafted == 0:
        return {"kind": "miss", "payload_ok": None}
    if drafted < expected:
        return {"kind": "incomplete", "payload_ok": None}
    return {
        "kind": "complete",
        "payload_ok": not wrong_patient(need, payloads) and bool(mod.accurate(need, payloads, now)),
    }


def run_once(
    mod: Any,
    name: str,
    event: Event,
    need: dict[str, Any],
    repeat: int,
    config: str,
    ward_now: str,
    llm: Llm,
    fhir: FhirClient,
) -> dict[str, Any]:
    result = run_tool_task(case_for(event, ward_now), watch_functions(), llm, fhir, CONFIGS[config])
    proposals = review.proposals(result.history, fhir)
    current = [p for p in proposals if p.findings is None and not p.superseded]  # what a clinician can approve
    payloads = [p.payload for p in current]
    return {
        "protocol": name,
        "event": f"{event.patient}:{event.protocol.code}",
        "repeat": repeat,
        "config": config,
        "need": need,
        "orders": len(payloads),
        "not_current": len(proposals) - len(payloads),  # gate-rejected or superseded drafts
        "model_calls": sum(m["role"] == "assistant" for m in result.transcript),
        "status": result.status.value,
        "format_retries": result.format_retries,
        **judged(mod, need, payloads, datetime.fromisoformat(ward_now)),
        "transcript": result.transcript,
    }


def run_all(name: str, config: str, out: Path, workers: int, llm: Llm, fhir: FhirClient) -> None:
    mod = module(name)
    spec = json.loads(ward_path(name).read_text())
    ward = load_ward(ward_path(name))
    needs = {e["patient"]: e for e in spec["events"]}
    done = {(r["event"], r["repeat"]) for r in load_rows(out)}
    jobs = [
        (e, needs[e.patient], k)
        for e in new_results(ward, fhir)
        if e.patient in needs
        for k in range(1, REPEATS[kind_of(needs[e.patient])] + 1)
        if (f"{e.patient}:{e.protocol.code}", k) not in done
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a") as sink, ThreadPoolExecutor(workers) as pool, contextlib.redirect_stdout(io.StringIO()):
        futures = [pool.submit(run_once, mod, name, e, n, k, config, ward.now, llm, fhir) for e, n, k in jobs]
        for future in futures:
            sink.write(json.dumps(future.result()) + "\n")
            sink.flush()


def script_rows(name: str) -> list[dict[str, Any]]:
    mod = module(name)
    spec = json.loads(ward_path(name).read_text())
    now, window, fhir = datetime.fromisoformat(spec["now"]), timedelta(hours=float(spec["window_hours"])), FhirClient()
    rows = []
    for need in spec["events"]:
        payloads = mod.rule_payloads(fhir, need["patient"], now, window)
        rows.append(
            {
                "event": need["patient"],
                "need": need,
                "model_calls": 0,
                "orders": len(payloads),
                **judged(mod, need, payloads, now),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ward").add_argument("name")
    sub.add_parser("script").add_argument("name")
    run = sub.add_parser("run")
    run.add_argument("name")
    run.add_argument("--config", choices=sorted(CONFIGS), default="watch")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--workers", type=int, default=8)
    run.add_argument("--model", required=True)
    run.add_argument("--base-url", required=True)
    run.add_argument("--key-file", type=Path, default=Path.home() / ".nebius_key")
    sub.add_parser("report").add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    if args.command == "ward":
        build(args.name)
    elif args.command == "script":
        print(describe(f"script {args.name}", totals(script_rows(args.name))))
    elif args.command == "run":
        llm = OpenAiCompatibleLlm(
            args.base_url, args.model, key_file=args.key_file, temperature=1.0, top_p=0.95, max_tokens=8192
        )
        run_all(args.name, args.config, args.out, args.workers, llm, FhirClient())
        print(describe(args.name, totals(load_rows(args.out))))
    else:
        for path in args.files:
            print(describe(path.stem, totals(load_rows(path))))


if __name__ == "__main__":
    main()
