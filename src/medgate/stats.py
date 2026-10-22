"""Paired statistics for comparing two arms on the same tasks."""

import random
from collections import defaultdict
from dataclasses import dataclass
from math import comb
from typing import Any

BOOTSTRAP_RESAMPLES = 2000
SEED = 0


@dataclass(frozen=True)
class Comparison:
    n: int
    rate_a: float
    rate_b: float
    diff: float  # b minus a, in absolute success rate
    ci95: tuple[float, float]
    only_b_correct: int
    only_a_correct: int
    mcnemar_p: float


def mcnemar_exact(only_b: int, only_a: int) -> float:
    """Two-sided exact McNemar test on the discordant pairs (a binomial test against 0.5)."""
    n = only_a + only_b
    if n == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(min(only_a, only_b) + 1)) / 2**n
    return min(1.0, 2 * tail)


def _paired_outcomes(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[tuple[bool, bool]]:
    by_task = {r["task_id"]: r["correct"] for r in a}
    return [(by_task[r["task_id"]], r["correct"]) for r in b if r["task_id"] in by_task]


def compare(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> Comparison:
    pairs = _paired_outcomes(a, b)
    n = len(pairs)
    if n == 0:
        raise ValueError("the two arms share no tasks")
    rng = random.Random(SEED)
    diffs = sorted(
        sum(pb - pa for pa, pb in (pairs[rng.randrange(n)] for _ in range(n))) / n for _ in range(BOOTSTRAP_RESAMPLES)
    )
    only_b = sum(pb and not pa for pa, pb in pairs)
    only_a = sum(pa and not pb for pa, pb in pairs)
    return Comparison(
        n=n,
        rate_a=sum(pa for pa, _ in pairs) / n,
        rate_b=sum(pb for _, pb in pairs) / n,
        diff=(only_b - only_a) / n,
        ci95=(diffs[int(0.025 * BOOTSTRAP_RESAMPLES)], diffs[int(0.975 * BOOTSTRAP_RESAMPLES) - 1]),
        only_b_correct=only_b,
        only_a_correct=only_a,
        mcnemar_p=mcnemar_exact(only_b, only_a),
    )


def by_category(records: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """Category -> (correct, total), ordered task1 .. task10."""
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in records:
        counts[r["category"]][0] += int(r["correct"])
        counts[r["category"]][1] += 1
    return {c: (v[0], v[1]) for c, v in sorted(counts.items(), key=lambda kv: int(kv[0][4:]))}


def stop_rule_met(c: Comparison, min_gain: float = 0.05) -> bool:
    """The frozen stop rule: the gain must reach min_gain and its confidence interval must exclude zero."""
    return c.diff >= min_gain and c.ci95[0] > 0


READ_ONLY_CATEGORIES = frozenset({"task1", "task2", "task4", "task6", "task7"})


def read_only_post_attempts(records: list[dict[str, Any]]) -> int:
    """Runs on categories that never allow a write where the agent still emitted a POST (the grader fails these)."""
    return sum(
        r["category"] in READ_ONLY_CATEGORIES
        and any(m["role"] == "agent" and "POST" in m["content"] for m in r["history"])
        for r in records
    )
