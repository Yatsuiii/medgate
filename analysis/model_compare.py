"""Run the watch on several Nemotron models over the same protocols, counting tokens per run.

Usage, from the repository root with the FHIR server up:
    uv run python -I analysis/model_compare.py run MODEL_ID LABEL --protocols a,b,c [--workers 8]
    uv run python -I analysis/model_compare.py report LABEL --protocols a,b,c

Rows go to runs/models/<protocol>_<label>.jsonl in the same format as bank_run.py plus a `usage` field (tokens the
endpoint reported for that run). Same sampling for every model (temperature 1.0, top_p 0.95, max_tokens 8192).
The client and agent are the frozen src/ code; the token count wraps the HTTP response and changes no behavior.
"""

import argparse
import contextlib
import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE), str(HERE / "protocols")]

import bank_run  # noqa: E402
from heldout_run import describe, load_rows, totals  # noqa: E402

from medgate.fhir import FhirClient  # noqa: E402
from medgate.llm import OpenAiCompatibleLlm  # noqa: E402
from medgate.watch import load_ward, new_results  # noqa: E402

BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
OUT = Path("runs/models")


class CountingLlm(OpenAiCompatibleLlm):
    """One instance per run: adds up the usage the endpoint reports for each request."""

    def __init__(self, model: str) -> None:
        super().__init__(
            BASE_URL, model, key_file=Path.home() / ".nebius_key", temperature=1.0, top_p=0.95, max_tokens=8192
        )
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def _post(self, request: dict[str, Any]) -> Any:
        response = super()._post(request)
        usage = response.json().get("usage") or {}
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)
        return response


def one(
    mod: Any, name: str, event: Any, need: dict[str, Any], repeat: int, model: str, ward_now: str, fhir: FhirClient
) -> dict[str, Any]:
    llm = CountingLlm(model)
    row = bank_run.run_once(mod, name, event, need, repeat, "watch", ward_now, llm, fhir)
    row["model"] = model
    row["usage"] = {"prompt": llm.prompt_tokens, "completion": llm.completion_tokens}
    return row


def run(model: str, label: str, protocols: list[str], workers: int, limit: int | None = None) -> None:
    fhir = FhirClient()
    OUT.mkdir(parents=True, exist_ok=True)
    for name in protocols:
        mod = bank_run.module(name)
        path = bank_run.ward_path(name)
        spec = json.loads(path.read_text())
        ward = load_ward(path)
        needs = {e["patient"]: e for e in spec["events"]}
        out = OUT / f"{name}_{label}.jsonl"
        done = {(r["event"], r["repeat"]) for r in load_rows(out)}
        jobs = [
            (e, needs[e.patient], k)
            for e in new_results(ward, fhir)
            if e.patient in needs
            for k in range(1, bank_run.REPEATS[bank_run.kind_of(needs[e.patient])] + 1)
            if (f"{e.patient}:{e.protocol.code}", k) not in done
        ]
        jobs = jobs[:limit] if limit else jobs
        with out.open("a") as sink, ThreadPoolExecutor(workers) as pool, contextlib.redirect_stdout(io.StringIO()):
            futures = [pool.submit(one, mod, name, e, n, k, model, ward.now, fhir) for e, n, k in jobs]
            for future in futures:
                sink.write(json.dumps(future.result()) + "\n")
                sink.flush()


def report(label: str, protocols: list[str]) -> None:
    prompt = completion = runs = 0
    for name in protocols:
        rows = load_rows(OUT / f"{name}_{label}.jsonl")
        print(describe(f"{label} {name}", totals(rows)))
        for r in rows:
            prompt += r["usage"]["prompt"]
            completion += r["usage"]["completion"]
            runs += 1
    print(
        f"{label}: {runs} runs, {prompt / max(runs, 1):.0f} prompt and "
        f"{completion / max(runs, 1):.0f} completion tokens per run"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("model")
    r.add_argument("label")
    r.add_argument("--protocols", required=True)
    r.add_argument("--workers", type=int, default=8)
    r.add_argument("--limit", type=int, default=None, help="run only the first N jobs of each protocol")
    p = sub.add_parser("report")
    p.add_argument("label")
    p.add_argument("--protocols", required=True)
    args = parser.parse_args()
    names = args.protocols.split(",")
    if args.command == "run":
        run(args.model, args.label, names, args.workers, args.limit)
    else:
        report(args.label, names)


if __name__ == "__main__":
    main()
