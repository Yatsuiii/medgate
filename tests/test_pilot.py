from pathlib import Path
from typing import Any

import pytest

from medgate.pilot import decision, pilot_task_ids, report

PREREG = Path(__file__).resolve().parents[1] / "docs" / "PILOT_PREREG.md"


def records(
    arm: str, model: str = "m", correct: set[str] | None = None, drop: str | None = None
) -> list[dict[str, Any]]:
    """One record per pilot task; `correct` is the set of task ids this arm gets right (default: all)."""
    right = set(pilot_task_ids()) if correct is None else correct
    return [
        {
            "task_id": t,
            "category": t.split("_")[0],
            "arm": arm,
            "model": model,
            "status": "completed",
            "result": "[1]",
            "correct": t in right,
            "rejected_posts": 0,
            "format_retries": 0,
            "rejected_reads": 0,
            "history": [],
        }
        for t in pilot_task_ids()
        if t != drop
    ]


def test_the_task_list_is_the_one_frozen_in_the_prereg() -> None:
    assert ",".join(pilot_task_ids()) in PREREG.read_text()


@pytest.mark.parametrize(
    ("correct", "starts"),
    [
        (30, "27 or more"),
        (27, "27 or more"),
        (26, "18 to 26"),
        (18, "18 to 26"),
        (17, "17 or fewer"),
        (0, "17 or fewer"),
    ],
)
def test_the_decision_thresholds_are_the_frozen_ones(correct: int, starts: str) -> None:
    assert decision(correct).startswith(starts)


def test_the_report_gives_counts_the_decision_and_the_failures_to_classify() -> None:
    ids = pilot_task_ids()
    t_right = set(ids[:20])
    text = report(records("A", correct=set(ids[:10])), records("T", correct=t_right))
    assert "A: 10/30 correct. T: 20/30 correct." in text
    assert "only T correct 10, only A correct 0" in text
    assert "decision (pre-registered): 18 to 26" in text
    assert f"  {ids[20]}  status completed" in text and f"  {ids[0]}  status" not in text


def test_a_missing_task_refuses_to_score() -> None:
    with pytest.raises(ValueError, match="missing"):
        report(records("A"), records("T", drop=pilot_task_ids()[3]))


def test_two_models_refuse_to_score() -> None:
    with pytest.raises(ValueError, match="different models"):
        report(records("A", model="m1"), records("T", model="m2"))


def test_a_duplicate_or_wrong_arm_refuses_to_score() -> None:
    with pytest.raises(ValueError, match="twice"):
        report(records("A") + records("A")[:1], records("T"))
    with pytest.raises(ValueError, match="expected T"):
        report(records("A"), records("A"))
