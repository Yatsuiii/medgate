"""Running one arm of the experiment over the benchmark tasks, with resumable JSON-lines output."""

import json
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from medgate import gates
from medgate.fhir import FhirClient
from medgate.gates import GateConfig
from medgate.grade import grade
from medgate.llm import Llm
from medgate.loop import TaskResult, run_task
from medgate.tool_agent import run_tool_task

ARMS: dict[str, GateConfig] = {
    "A": gates.REFERENCE,
    "B1": gates.FORMAT_ONLY,
    "B2": gates.WITH_VALIDATION,
    "B3": gates.FULL,
}
# Native tool calling (the MedAgentBench v2-style agent). In T the format retry is the reminder sent when a reply has
# no tool call; TG adds the payload gate and the evidence gate, which here also covers patient-scoped searches.
TOOL_ARMS: dict[str, GateConfig] = {"T": gates.FORMAT_ONLY, "TG": gates.FULL}
Grader = Callable[[dict[str, Any], TaskResult], bool]


def load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def record_of(arm: str, model: str, case: dict[str, Any], result: TaskResult, correct: bool) -> dict[str, Any]:
    return {
        "task_id": case["id"],
        "category": case["id"].split("_")[0],
        "arm": arm,
        "model": model,
        "status": result.status.value,
        "result": result.result,
        "correct": correct,
        "rejected_posts": result.rejected_posts,
        "format_retries": result.format_retries,
        "rejected_reads": result.rejected_reads,
        "history": result.history,
        "transcript": result.transcript,
    }


def run_one(arm: str, case: dict[str, Any], functions: list[dict[str, Any]], llm: Llm, fhir: FhirClient) -> TaskResult:
    if arm in TOOL_ARMS:
        return run_tool_task(case, functions, llm, fhir, TOOL_ARMS[arm])
    return run_task(case, functions, llm, fhir, ARMS[arm])


def run_arm(
    arm: str,
    model: str,
    tasks: Sequence[dict[str, Any]],
    functions: list[dict[str, Any]],
    llm_factory: Callable[[], Llm],
    fhir: FhirClient,
    out_path: Path,
    grader: Grader = grade,
    pause_s: float = 0.0,
) -> list[dict[str, Any]]:
    """Run every task not already in out_path, appending one line per finished task.

    An LLM error aborts the run and leaves earlier lines intact, so rerunning resumes where it stopped.
    """
    finished = {r["task_id"] for r in load_records(out_path) if r["arm"] == arm and r["model"] == model}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a") as out:
        for case in tasks:
            if case["id"] in finished:
                continue
            result = run_one(arm, case, functions, llm_factory(), fhir)
            out.write(json.dumps(record_of(arm, model, case, result, grader(case, result))) + "\n")
            out.flush()
            time.sleep(pause_s)
    return [r for r in load_records(out_path) if r["arm"] == arm and r["model"] == model]
