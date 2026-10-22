"""Runner, statistics and CLI. Pure tests use a stub grader; the CLI dry run uses the live server and real grader."""

import json
from math import comb
from pathlib import Path
from typing import Any

import pytest

from medgate import stats
from medgate.cli import main
from medgate.fhir import FhirClient, GetResult
from medgate.llm import ScriptedLlm
from medgate.loop import TaskResult
from medgate.runner import ARMS, load_records, run_arm

FUNCS: list[dict[str, Any]] = []


def case(i: int, category: int = 1) -> dict[str, Any]:
    return {"id": f"task{category}_{i}", "instruction": "Q", "context": "", "sol": []}


class FakeFhir(FhirClient):
    def __init__(self) -> None:  # no network
        pass

    def get(self, url: str) -> GetResult:
        return GetResult(data="x")


def rec(task_id: str, correct: bool, history: list[dict[str, str]] | None = None, **kw: Any) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "category": task_id.split("_")[0],
        "arm": "A",
        "model": "m",
        "status": "completed",
        "result": "[]",
        "correct": correct,
        "rejected_posts": 0,
        "format_retries": 0,
        "history": history or [],
        **kw,
    }


# --- runner -----------------------------------------------------------------------------------------------------


def test_arms_map_to_the_frozen_gate_configurations() -> None:
    assert not any(vars(ARMS["A"]).values())
    assert ARMS["B1"].format_retry and not ARMS["B1"].validate_payload
    assert ARMS["B2"].validate_payload and not ARMS["B2"].require_evidence
    assert ARMS["B3"].require_evidence


def test_run_arm_writes_one_line_per_task_with_the_grader_outcome(tmp_path: Path) -> None:
    out = tmp_path / "runs" / "A.jsonl"
    tasks = [case(1), case(2)]
    records = run_arm(
        "A",
        "m",
        tasks,
        FUNCS,
        lambda: ScriptedLlm(["FINISH([])"]),
        FakeFhir(),
        out,
        grader=lambda c, r: c["id"] == "task1_1",
    )
    assert [r["correct"] for r in records] == [True, False]
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["task_id"] for r in lines] == ["task1_1", "task1_2"]
    assert lines[0]["arm"] == "A" and lines[0]["model"] == "m" and lines[0]["history"][0]["role"] == "user"


def test_run_arm_resumes_without_redoing_finished_tasks(tmp_path: Path) -> None:
    out = tmp_path / "A.jsonl"
    calls: list[str] = []

    def grader(c: dict[str, Any], r: TaskResult) -> bool:
        calls.append(c["id"])
        return True

    def llm() -> ScriptedLlm:
        return ScriptedLlm(["FINISH([])"])

    run_arm("A", "m", [case(1)], FUNCS, llm, FakeFhir(), out, grader=grader)
    records = run_arm("A", "m", [case(1), case(2)], FUNCS, llm, FakeFhir(), out, grader=grader)
    assert calls == ["task1_1", "task1_2"] and len(records) == 2


def test_run_arm_keeps_finished_lines_when_the_llm_fails(tmp_path: Path) -> None:
    out = tmp_path / "A.jsonl"
    replies = iter([ScriptedLlm(["FINISH([])"]), ScriptedLlm([])])  # the second task has no reply: AssertionError
    with pytest.raises(AssertionError):
        run_arm("A", "m", [case(1), case(2)], FUNCS, lambda: next(replies), FakeFhir(), out, grader=lambda c, r: True)
    assert [r["task_id"] for r in load_records(out)] == ["task1_1"]


def test_runs_for_different_models_do_not_resume_each_other(tmp_path: Path) -> None:
    out = tmp_path / "A.jsonl"
    for model in ("m1", "m2"):
        run_arm(
            "A", model, [case(1)], FUNCS, lambda: ScriptedLlm(["FINISH([])"]), FakeFhir(), out, grader=lambda c, r: True
        )
    assert [r["model"] for r in load_records(out)] == ["m1", "m2"]


# --- statistics -------------------------------------------------------------------------------------------------


def test_mcnemar_matches_the_binomial_formula() -> None:
    expected = 2 * sum(comb(12, k) for k in range(3)) / 2**12
    assert stats.mcnemar_exact(10, 2) == pytest.approx(expected)
    assert stats.mcnemar_exact(0, 0) == 1.0 and stats.mcnemar_exact(5, 5) == 1.0


def test_compare_counts_discordant_pairs_and_the_difference() -> None:
    a = [rec(f"task1_{i}", i < 40) for i in range(100)]  # A correct on 0..39
    b = [rec(f"task1_{i}", i < 20 or 40 <= i < 70) for i in range(100)]  # B keeps 0..19, adds 40..69, loses 20..39
    c = stats.compare(a, b)
    assert (c.n, c.only_b_correct, c.only_a_correct) == (100, 30, 20)
    assert c.rate_a == pytest.approx(0.40) and c.rate_b == pytest.approx(0.50) and c.diff == pytest.approx(0.10)


def test_bootstrap_is_deterministic_and_brackets_the_difference() -> None:
    a = [rec(f"task1_{i}", i % 2 == 0) for i in range(200)]
    b = [rec(f"task1_{i}", i % 2 == 0 or i % 5 == 0) for i in range(200)]
    first, second = stats.compare(a, b), stats.compare(a, b)
    assert first == second and first.ci95[0] <= first.diff <= first.ci95[1]


def test_stop_rule_needs_both_a_five_point_gain_and_a_ci_above_zero() -> None:
    a = [rec(f"task1_{i}", False) for i in range(300)]
    clear_gain = [rec(f"task1_{i}", i < 60) for i in range(300)]  # +20 points
    small_gain = [rec(f"task1_{i}", i < 6) for i in range(300)]  # +2 points
    assert stats.stop_rule_met(stats.compare(a, clear_gain)) is True
    assert stats.stop_rule_met(stats.compare(a, small_gain)) is False


def test_compare_refuses_arms_with_no_shared_tasks() -> None:
    with pytest.raises(ValueError):
        stats.compare([rec("task1_1", True)], [rec("task1_2", True)])


def test_by_category_is_ordered_numerically() -> None:
    rows = [rec("task10_1", True), rec("task2_1", False), rec("task2_2", True)]
    assert list(stats.by_category(rows).items()) == [("task2", (1, 2)), ("task10", (1, 1))]


def test_read_only_post_attempts_counts_only_read_only_categories() -> None:
    attempt = [{"role": "agent", "content": "POST http://x/fhir/ServiceRequest\n{}"}]
    rows = [rec("task1_1", False, attempt), rec("task3_1", False, attempt), rec("task7_1", True, [])]
    assert stats.read_only_post_attempts(rows) == 1


# --- command line -----------------------------------------------------------------------------------------------


def test_cli_refuses_a_real_run_without_a_key(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    status = main(
        ["run", "--arm", "A", "--model", "m", "--out", str(tmp_path / "A.jsonl"), "--key-file", str(tmp_path / "none")]
    )
    assert status == 2 and "refusing to start" in capsys.readouterr().err


@pytest.mark.live
def test_cli_dry_run_and_compare_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    if not FhirClient().is_up():
        pytest.skip("needs the FHIR server")
    for arm in ("A", "B1"):
        assert (
            main(
                [
                    "run",
                    "--arm",
                    arm,
                    "--model",
                    "dry",
                    "--out",
                    str(tmp_path / f"{arm}.jsonl"),
                    "--limit",
                    "12",
                    "--dry-run",
                ]
            )
            == 0
        )
    capsys.readouterr()
    assert main(["compare", str(tmp_path / "A.jsonl"), str(tmp_path / "B1.jsonl")]) == 0
    out = capsys.readouterr().out
    assert "n=12" in out and "McNemar" in out and "stop rule" in out and "task1" in out
