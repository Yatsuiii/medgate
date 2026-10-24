"""Replay saved order sets through a second model that checks them against the protocol (docs/VERIFIER_PREREG.md).

Usage, from the repository root with the FHIR server up and a key file:
    uv run python -I analysis/verifier_replay.py sample
    uv run python -I analysis/verifier_replay.py run MODEL_ID LABEL [--workers 6]
    uv run python -I analysis/verifier_replay.py report LABEL
The verifier sees the protocol text, the ward time, raw record values and the drafted orders. Never the expected
answer, the judge or whether the run failed.
"""

import argparse
import json
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE), str(HERE / "protocols")]

import bank_run  # noqa: E402
import confirm3_rescore as rescore  # noqa: E402

from medgate.fhir import FhirClient  # noqa: E402
from medgate.llm import OpenAiCompatibleLlm  # noqa: E402

NAMES = ["sodium_high", "phosphate_oral", "lab_pair_urgent"]
OUT = Path("runs/verifier")
BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
FACTS = {
    "value": "the trigger result",
    "cr": "newest creatinine (mg/dL)",
    "egfr": "newest eGFR",
    "plt": "newest platelets",
}
SYSTEM = (
    "You check a drafted set of orders against a unit protocol. Use only the protocol text, the record values and the "
    "drafted orders below. Decide whether the drafted set is exactly what the protocol requires for this patient: "
    "the right orders, no missing order, no extra order, and each order's code, dose, route, timing, duration and "
    "priority as the protocol states. Orders must be absent if an exclusion holds or the protocol requires none. "
    'Reply with one JSON object only: {"verdict": "ok" or "problem", "reason": "one sentence"}.'
)


class Verifier(OpenAiCompatibleLlm):
    def __init__(self, model: str) -> None:
        super().__init__(
            BASE_URL, model, key_file=Path.home() / ".nebius_key", temperature=0.0, top_p=1.0, max_tokens=2000
        )
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def _post(self, request: dict[str, Any]) -> Any:
        response = super()._post(request)
        usage = response.json().get("usage") or {}
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)
        return response


def rows_for(name: str) -> list[dict[str, Any]]:
    path = Path(f"runs/bank/{name}_confirm2_watch.jsonl")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def truth(row: dict[str, Any]) -> str | None:
    """failing, correct, or None when the run is neither (not used)."""
    need_orders = row["need"]["orders"] > 0
    if need_orders:
        if row["kind"] in ("miss", "incomplete") or (row["kind"] == "complete" and not row["payload_ok"]):
            return "failing"
        return "correct" if row["kind"] == "complete" else None
    return "correct" if row["kind"] in ("held_ok", "ok_none") else None


def sample() -> None:
    rng = random.Random(0)
    failing, ok_sets, ok_empty = [], [], []
    for name in NAMES:
        for r in rows_for(name):
            key = {"protocol": name, "event": r["event"], "repeat": r["repeat"]}
            t = truth(r)
            if t == "failing":
                failing.append(key)
            elif t == "correct":
                (ok_sets if r["need"]["orders"] > 0 else ok_empty).append(key)
    chosen = failing + rng.sample(ok_sets, 60) + rng.sample(ok_empty, 20)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sample.json").write_text(json.dumps(chosen, indent=1) + "\n")
    print(f"{len(failing)} failing, 60 correct sets, 20 correct empty: {len(chosen)} sampled")


def prompt_for(row: dict[str, Any], protocol_text: str, payloads: list[dict[str, Any]]) -> str:
    facts = "\n".join(f"- {label}: {row['need'][key]}" for key, label in FACTS.items() if key in row["need"])
    orders = "\n".join(json.dumps(p) for p in payloads) if payloads else "No orders drafted."
    return (
        f"Protocol:\n{protocol_text}\n\nWard time: 2023-11-13T10:15:00+00:00\n\nRecord values:\n{facts}\n\n"
        f"Drafted orders:\n{orders}"
    )


def parse(text: str) -> tuple[str, str]:
    match = re.search(r'"verdict"\s*:\s*"(ok|problem)"', text)
    reason = re.search(r'"reason"\s*:\s*"([^"]*)"', text)
    return (match.group(1) if match else "unparsed", reason.group(1) if reason else text[:200])


def run(model: str, label: str, workers: int, max_completion: int | None = None) -> None:
    keys = json.loads((OUT / "sample.json").read_text())
    fhir = FhirClient()
    texts = {n: json.loads(bank_run.ward_path(n).read_text())["protocols"][0]["text"] for n in NAMES}
    by_name = {n: {(r["event"], r["repeat"]): r for r in rows_for(n)} for n in NAMES}
    out = OUT / f"{label}.jsonl"
    done = (
        {(d["protocol"], d["event"], d["repeat"]) for d in map(json.loads, out.read_text().splitlines())}
        if out.exists()
        else set()
    )

    def one(key: dict[str, Any]) -> dict[str, Any]:
        row = by_name[key["protocol"]][(key["event"], key["repeat"])]
        payloads = rescore.current_payloads(row["transcript"], fhir)
        llm = Verifier(model)
        reply = llm.complete(
            [{"role": "user", "content": SYSTEM + "\n\n" + prompt_for(row, texts[key["protocol"]], payloads)}]
        )
        verdict, reason = parse(reply)
        return {
            **key,
            "truth": truth(row),
            "kind": row["kind"],
            "verdict": verdict,
            "reason": reason,
            "prompt_tokens": llm.prompt_tokens,
            "completion_tokens": llm.completion_tokens,
        }

    todo = [k for k in keys if (k["protocol"], k["event"], k["repeat"]) not in done]
    spent = 0
    with out.open("a") as sink, ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(one, k) for k in todo]
        for future in futures:
            result = future.result()
            sink.write(json.dumps(result) + "\n")
            sink.flush()
            spent += result["completion_tokens"]
            if max_completion is not None and spent > max_completion:  # a spend cap: stop what has not started
                for pending in futures:
                    pending.cancel()
                print(f"stopped: {spent} completion tokens passed the cap of {max_completion}")
                break


def report(label: str) -> None:
    rows = [json.loads(line) for line in (OUT / f"{label}.jsonl").read_text().splitlines()]
    fail = [r for r in rows if r["truth"] == "failing"]
    good = [r for r in rows if r["truth"] == "correct"]
    caught = sum(r["verdict"] == "problem" for r in fail)
    alarms = sum(r["verdict"] == "problem" for r in good)
    unparsed = sum(r["verdict"] == "unparsed" for r in rows)
    print(
        f"{label}: failing sets caught {caught}/{len(fail)} ({caught / max(len(fail), 1):.0%}); "
        f"correct sets flagged {alarms}/{len(good)} ({alarms / max(len(good), 1):.0%}); unparsed {unparsed}"
    )
    for kind in ("miss", "incomplete", "complete"):
        part = [r for r in fail if r["kind"] == kind]
        print(f"   {kind}: caught {sum(r['verdict'] == 'problem' for r in part)}/{len(part)}")
    p = sum(r["prompt_tokens"] for r in rows)
    c = sum(r["completion_tokens"] for r in rows)
    print(f"   tokens: {p} prompt, {c} completion over {len(rows)} calls")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sample")
    r = sub.add_parser("run")
    r.add_argument("model")
    r.add_argument("label")
    r.add_argument("--workers", type=int, default=6)
    r.add_argument("--max-completion", type=int, default=None, help="stop after this many completion tokens")
    sub.add_parser("report").add_argument("label")
    args = parser.parse_args()
    if args.command == "sample":
        sample()
    elif args.command == "run":
        run(args.model, args.label, args.workers, args.max_completion)
    else:
        report(args.label)


if __name__ == "__main__":
    main()
