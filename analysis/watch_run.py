"""The results watch on a model, under docs/WATCH_RUN_PREREG.md: arm TG on each new result of the demo ward.

Three runs per event.

Events with a benchmark case (a task 9 patient for potassium, a task 5 patient for magnesium) are graded by the
benchmark's grader. The others must order nothing. Every drafted order must cite its triggering result.

Usage, from the repository root with the FHIR server and vendor/refsol.py in place:
    uv run python -I analysis/watch_run.py --out runs/watch_TG.jsonl --model <MODEL> --base-url <URL> \
        --key-file <FILE> --temperature 1.0 --top-p 0.95 --max-tokens 8192
    uv run python -I analysis/watch_run.py --out /tmp/x.jsonl --replay   # plumbing check, scripted runs, no model
The run is resumable. `--summary-only` prints the criteria from an existing output file.
"""

import argparse
import contextlib
import io
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from medgate import review
from medgate.fhir import FhirClient
from medgate.gates import FULL
from medgate.grade import grade
from medgate.llm import Llm, OpenAiCompatibleLlm
from medgate.tasks import load_functions, load_tasks
from medgate.tool_agent import run_tool_task
from medgate.watch import Event, case_for, load_ward, new_results
from medgate.web import load_replay

DEMO = Path("demo")
CATEGORY_OF = {"K": "task9", "MG": "task5"}
SUPPORT_AT, FAIL_AT = 22, 13  # of 27 graded runs, from the pre-registration


def benchmark_case(event: Event) -> dict[str, Any] | None:
    prefix = f"{CATEGORY_OF[event.protocol.code]}_"
    return next((c for c in load_tasks() if c["id"].startswith(prefix) and c["eval_MRN"] == event.patient), None)


def run_once(event: Event, repeat: int, now: str, llm: Llm, fhir: FhirClient) -> dict[str, Any]:
    case = case_for(event, now)
    result = run_tool_task(case, load_functions(), llm, fhir, FULL)
    proposals = review.proposals(result.history, fhir)
    cite = [{"reference": f"Observation/{event.result['id']}"}]
    benchmark = benchmark_case(event)
    return {
        "event": f"{event.patient}:{event.protocol.code}",
        "repeat": repeat,
        "status": result.status.value,
        "answer": result.result,
        "orders": len(proposals),
        "all_cite_the_result": all(p.payload.get("reasonReference") == cite for p in proposals),
        "gate_findings": sum(p.findings is not None for p in proposals),
        "format_retries": result.format_retries,
        "graded": None if benchmark is None else bool(grade(benchmark, result)),
        "transcript": result.transcript,  # for reading failures; the frozen watch run predates this field
    }


def load_done(path: Path) -> dict[tuple[str, int], dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    return {(r["event"], r["repeat"]): r for r in rows}


def run_all(
    llm_for: Callable[[dict[str, Any]], Llm], fhir: FhirClient, out: Path, repeats: int, workers: int, only: set[str]
) -> None:
    ward = load_ward(DEMO / "ward.json")
    done = load_done(out)
    jobs = [
        (e, k)
        for e in new_results(ward, fhir)
        for k in range(1, repeats + 1)
        if (f"{e.patient}:{e.protocol.code}", k) not in done and (not only or f"{e.patient}:{e.protocol.code}" in only)
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a") as sink, ThreadPoolExecutor(workers) as pool, contextlib.redirect_stdout(io.StringIO()):
        futures = [pool.submit(run_once, e, k, ward.now, llm_for(case_for(e, ward.now)), fhir) for e, k in jobs]
        for future in futures:
            sink.write(json.dumps(future.result()) + "\n")
            sink.flush()


def summary(rows: list[dict[str, Any]]) -> str:
    graded = [r for r in rows if r["graded"] is not None]
    quiet = [r for r in rows if r["graded"] is None]  # no benchmark case: the protocol orders nothing for these
    correct = sum(r["graded"] for r in graded)
    wrong_orders = sum(r["orders"] > 0 for r in quiet)
    cited = all(r["all_cite_the_result"] for r in rows)
    if correct >= SUPPORT_AT and wrong_orders == 0 and cited:
        verdict = "SUPPORTS the product claim"
    elif correct <= FAIL_AT:
        verdict = "FAILS"
    else:
        verdict = "BETWEEN (CAUTION): classify the failures before any change"
    lines = [
        f"{len(rows)} runs: {len(graded)} graded by the benchmark, {len(quiet)} that must order nothing",
        f"graded correct: {correct}/{len(graded)} (supports at {SUPPORT_AT} or more, fails at {FAIL_AT} or fewer)",
        f"orders on the must-order-nothing runs: {wrong_orders} of {len(quiet)} (supports needs 0)",
        f"every drafted order cites its triggering result: {cited}",
        f"gate rejections {sum(r['gate_findings'] for r in rows)}, "
        f"format retries {sum(r['format_retries'] for r in rows)}",
        f"not completed: {sum(r['status'] != 'completed' for r in rows)}",
        f"verdict by the pre-registered criteria: {verdict}",
        "per event (graded correct or orders drafted, over runs):",
    ]
    for event in sorted({r["event"] for r in rows}):
        mine = [r for r in rows if r["event"] == event]
        score = (
            f"{sum(r['graded'] for r in mine)}/{len(mine)} correct"
            if mine[0]["graded"] is not None
            else f"{sum(r['orders'] > 0 for r in mine)}/{len(mine)} drafted orders (should be 0)"
        )
        lines.append(f"  {event}: {score}, orders per run {[r['orders'] for r in mine]}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--replay", action="store_true", help="the scripted demo runs instead of a model (plumbing)")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--only", default="", help="comma-separated events like S6550627:K, for a diagnostic run")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--key-file", type=Path, default=Path.home() / ".nebius_key")
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--max-tokens", type=int, default=8192)
    args = parser.parse_args()
    if not args.summary_only:
        if args.replay:
            replay = load_replay(DEMO / "replay.json")
            llm_for: Callable[[dict[str, Any]], Llm] = replay.llm_for
        else:
            model = OpenAiCompatibleLlm(
                args.base_url,
                args.model,
                key_file=args.key_file,
                temperature=args.temperature,
                top_p=args.top_p,
                max_tokens=args.max_tokens,
            )
            llm_for = lambda case: model  # noqa: E731, ARG005 - one client for every run
        run_all(llm_for, FhirClient(), args.out, args.repeats, args.workers, set(filter(None, args.only.split(","))))
    print(summary(list(load_done(args.out).values())))


if __name__ == "__main__":
    main()
