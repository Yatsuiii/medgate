"""Command line: run one arm of the experiment, compare two finished runs, report the pilot, or serve the screen."""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from medgate import pilot, stats
from medgate.fhir import FhirClient
from medgate.llm import Llm, OpenAiCompatibleLlm, ScriptedLlm, ToolCall, Turn
from medgate.protocol import MAX_ROUNDS
from medgate.runner import ARMS, TOOL_ARMS, load_records, run_arm
from medgate.tasks import load_functions, load_tasks, watch_functions
from medgate.watch import load_ward
from medgate.web import ReviewApp, ReviewServer, load_replay

DEFAULT_KEY_FILE = Path.home() / ".nebius_key"


def _model(args: argparse.Namespace) -> Llm | None:
    """The configured model endpoint, or None when the base url or the key file is missing."""
    if not args.key_file.exists() or not args.base_url:
        return None
    return OpenAiCompatibleLlm(
        args.base_url,
        args.model,
        key_file=args.key_file,
        temperature=args.temperature,
        top_p=args.top_p,
        max_tokens=args.max_tokens,
    )


def _dry_run_llm(arm: str) -> Llm:
    """A scripted agent that only finishes with an empty answer, to check the plumbing without a model."""
    if arm in TOOL_ARMS:
        return ScriptedLlm([Turn(calls=(ToolCall("dry", "finish", '{"answer": []}'),))] * MAX_ROUNDS)
    return ScriptedLlm(["FINISH([])"] * MAX_ROUNDS)


def _run(args: argparse.Namespace) -> int:
    live = None if args.dry_run else _model(args)
    if live is None and not args.dry_run:
        print(f"refusing to start: need --base-url and a key file at {args.key_file}", file=sys.stderr)
        return 2
    tasks = load_tasks()
    if args.tasks:
        by_id = {t["id"]: t for t in tasks}
        wanted = args.tasks.split(",")
        if unknown := [i for i in wanted if i not in by_id]:
            print(f"unknown task ids: {', '.join(unknown)}", file=sys.stderr)
            return 2
        tasks = [by_id[i] for i in wanted]
    tasks = tasks[: args.limit]
    fhir = FhirClient()
    if not fhir.is_up():
        print("the FHIR server is not answering on localhost:8080", file=sys.stderr)
        return 2

    def factory() -> Llm:
        return live if live is not None else _dry_run_llm(args.arm)

    records = run_arm(args.arm, args.model, tasks, load_functions(), factory, fhir, args.out, pause_s=args.pause)
    correct = sum(r["correct"] for r in records)
    print(f"arm {args.arm} model {args.model}: {correct}/{len(records)} correct, written to {args.out}")
    return 0


def _pilot(args: argparse.Namespace) -> int:
    try:
        print(pilot.report(load_records(args.a), load_records(args.t)))
    except ValueError as exc:
        print(f"not reporting: {exc}", file=sys.stderr)
        return 2
    return 0


def _compare(args: argparse.Namespace) -> int:
    a, b = load_records(args.a), load_records(args.b)
    c = stats.compare(a, b)
    print(
        f"n={c.n}  A={c.rate_a:.3f}  B={c.rate_b:.3f}  B-A={c.diff:+.3f}  95% CI [{c.ci95[0]:+.3f}, {c.ci95[1]:+.3f}]"
    )
    print(
        f"discordant: only B correct {c.only_b_correct}, only A correct {c.only_a_correct}, "
        f"McNemar exact p={c.mcnemar_p:.4f}"
    )
    print(f"stop rule (gain >= 5 points and CI above zero): {'MET' if stats.stop_rule_met(c) else 'NOT MET'}")
    print("category   A        B")
    cats_a, cats_b = stats.by_category(a), stats.by_category(b)
    for cat in cats_a:
        (ca, na), (cb, nb) = cats_a[cat], cats_b.get(cat, (0, 0))
        print(f"{cat:<9} {ca:>2}/{na:<3}  {cb:>2}/{nb:<3}")
    for name, rows in (("A", a), ("B", b)):
        print(
            f"{name}: format retries {sum(r['format_retries'] for r in rows)}, "
            f"rejected POSTs {sum(r['rejected_posts'] for r in rows)}, "
            f"rejected searches {sum(r.get('rejected_reads', 0) for r in rows)}, "
            f"POST attempts on read-only categories {stats.read_only_post_attempts(rows)}"
        )
    return 0


def _serve(args: argparse.Namespace) -> int:
    llm_for: Callable[[dict[str, Any]], Llm]
    if args.replay is not None:
        replay = load_replay(args.replay)
        llm_for = replay.llm_for
        mode = {"replay": True, "model": "", "ask": {"context": replay.context, "question": replay.question}}
    elif (live := _model(args)) is not None:
        model = live
        llm_for = lambda case: model  # noqa: E731 - one model for every task
        mode = {"replay": False, "model": args.model, "ask": {"context": "", "question": ""}}
    else:
        print(
            f"refusing to start: need --base-url and a key file at {args.key_file}, or --replay FILE", file=sys.stderr
        )
        return 2
    fhir = FhirClient()
    if not fhir.is_up():
        print("the FHIR server is not answering on localhost:8080", file=sys.stderr)
        return 2
    ward = load_ward(args.ward) if args.ward is not None else None
    server = ReviewServer(ReviewApp(llm_for, fhir, watch_functions(), mode, ward), args.port)
    print(f"review screen: http://127.0.0.1:{server.server_port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _add_model_options(parser: argparse.ArgumentParser, model_required: bool) -> None:
    parser.add_argument("--model", required=model_required, default="")
    parser.add_argument("--base-url", default="", help="OpenAI-compatible endpoint, for example the Token Factory URL")
    parser.add_argument("--key-file", type=Path, default=DEFAULT_KEY_FILE)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=None, help="cap on reply length; reasoning models need room")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="medgate")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run one arm over the benchmark tasks (resumable)")
    run.add_argument("--arm", choices=sorted(ARMS | TOOL_ARMS), required=True)
    _add_model_options(run, model_required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--tasks", default="", help="comma-separated task ids to run, in this order (default: all)")
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--pause", type=float, default=0.0)
    run.add_argument("--dry-run", action="store_true", help="scripted agent that only answers FINISH([]), for plumbing")
    compare = sub.add_parser("compare", help="paired comparison of two finished runs")
    compare.add_argument("a", type=Path)
    compare.add_argument("b", type=Path)
    pilot_cmd = sub.add_parser("pilot", help="the pilot's results and its pre-registered decision, from arms A and T")
    pilot_cmd.add_argument("a", type=Path, help="the arm A run file")
    pilot_cmd.add_argument("t", type=Path, help="the arm T run file")
    serve = sub.add_parser("serve", help="the review screen: ask, review proposed writes, approve")
    _add_model_options(serve, model_required=False)
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--replay", type=Path, default=None, help="scripted agent turns from a file (demo/), no model")
    serve.add_argument("--ward", type=Path, default=None, help="patients and protocols to watch (demo/ward.json)")
    args = parser.parse_args(argv)
    commands = {"run": _run, "compare": _compare, "pilot": _pilot, "serve": _serve}
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
