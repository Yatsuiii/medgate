"""The pilot's report: applies the decision rule frozen in docs/PILOT_PREREG.md to two finished runs.

The report only reads run files. It refuses to score a partial pilot: every one of the 30 pre-registered tasks must be
present in both arms, from one model each, so a missing task cannot quietly raise or lower a count.
"""

import random
from typing import Any

from medgate import stats

ARM_NAMES = ("A", "T")


def pilot_task_ids() -> list[str]:
    """The 30 pre-registered tasks: one Random(0) used in sequence, 3 sorted picks from 1..30 per category 1 to 10."""
    rng = random.Random(0)
    return [f"task{c}_{n}" for c in range(1, 11) for n in sorted(rng.sample(range(1, 31), 3))]


def decision(t_correct: int) -> str:
    """The pre-registered threshold on arm T's correct count out of 30, applied as written."""
    if t_correct >= 27:
        return "27 or more: little room for gates. The story is open-model parity and gate claims are dropped."
    if t_correct >= 18:
        return (
            "18 to 26: classify T's failures. Build gates only for classes that could be worth 5 points or more "
            "on the full 300."
        )
    return "17 or fewer: read 5 failing transcripts for harness bugs first, then consider a larger Nemotron model."


def _checked(arm: str, records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The arm's records by task id, or a ValueError saying what makes this run unfit to score."""
    expected = pilot_task_ids()
    by_task: dict[str, dict[str, Any]] = {}
    for r in records:
        if r["arm"] != arm:
            raise ValueError(f"{r['task_id']} is arm {r['arm']}, expected {arm}")
        if r["task_id"] in by_task:
            raise ValueError(f"arm {arm} has {r['task_id']} twice")
        by_task[r["task_id"]] = r
    missing = [t for t in expected if t not in by_task]
    extra = sorted(set(by_task) - set(expected))
    if missing or extra:
        raise ValueError(f"arm {arm}: missing {missing or 'none'}, not in the pilot {extra or 'none'}")
    models = {r["model"] for r in records}
    if len(models) != 1:
        raise ValueError(f"arm {arm} mixes models {sorted(models)}")
    return by_task


def report(a_records: list[dict[str, Any]], t_records: list[dict[str, Any]]) -> str:
    """The pilot's results as text: counts, discordant pairs, the decision, and T's failures to classify by hand."""
    a, t = _checked("A", a_records), _checked("T", t_records)
    models = {next(iter(a.values()))["model"], next(iter(t.values()))["model"]}
    if len(models) != 1:
        raise ValueError(f"the two arms ran different models: {sorted(models)}")
    ids = pilot_task_ids()
    a_list, t_list = [a[i] for i in ids], [t[i] for i in ids]
    comparison = stats.compare(a_list, t_list)
    t_correct = sum(r["correct"] for r in t_list)
    lines = [
        f"model {next(iter(models))}, {len(ids)} tasks, one run each",
        f"A: {sum(r['correct'] for r in a_list)}/30 correct. T: {t_correct}/30 correct.",
        f"paired: only T correct {comparison.only_b_correct}, only A correct {comparison.only_a_correct}, "
        f"McNemar exact p={comparison.mcnemar_p:.4f}. With 30 tasks a 95% interval is about plus or minus 17 points.",
        "category   A       T",
    ]
    cats_a, cats_t = stats.by_category(a_list), stats.by_category(t_list)
    lines += [f"{c:<9} {cats_a[c][0]}/{cats_a[c][1]}   {cats_t[c][0]}/{cats_t[c][1]}" for c in cats_a]
    for name, rows in (("A", a_list), ("T", t_list)):
        lines.append(
            f"{name}: format retries {sum(r['format_retries'] for r in rows)}, rejected POSTs "
            f"{sum(r['rejected_posts'] for r in rows)}, POST attempts on read-only categories "
            f"{stats.read_only_post_attempts(rows)}, not finished {sum(r['status'] != 'completed' for r in rows)}"
        )
    lines += [
        "",
        f"decision (pre-registered): {decision(t_correct)}",
        "",
        "T's failures, to classify by hand (8 classes):",
    ]
    failures = [r for r in t_list if not r["correct"]]
    lines += [f"  {r['task_id']}  status {r['status']}  answer {str(r['result'])[:80]}" for r in failures] or ["  none"]
    return "\n".join(lines)
