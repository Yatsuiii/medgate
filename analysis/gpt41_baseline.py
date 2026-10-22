"""GPT-4.1 on MedAgentBench's reference loop: what fails, why, and whether medgate's grader agrees with the published.

The run files come from the MedAgentBench v2 repository (outputs/MedAgentBenchv1-mookass, GPT-4.1, temperature 0, the
original 300 tasks, the reference loop). They carry no license, so they stay outside this repository.

Usage, from the repository root with the FHIR server and vendor/refsol.py in place:
    uv run python -I analysis/gpt41_baseline.py <directory with runs.jsonl and overall.json>

Prints counts only. The output is deterministic for a given server state.
"""

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from medgate.fhir import FhirClient
from medgate.grade import grade
from medgate.loop import Status, TaskResult
from medgate.protocol import FHIR_BASE
from medgate.tasks import load_tasks
from medgate.tool_agent import answer_problems

NOW_TEXT = "2023-11-13T10:15:00+00:00"
READ_ONLY = {"task1", "task2", "task4", "task6", "task7"}
LAB_CODE = {"task4": "MG", "task5": "MG", "task6": "GLU", "task7": "GLU", "task9": "K", "task10": "A1C"}
EXACT_TIME_FIELD = {"task3": "effectiveDateTime", "task8": "authoredOn", "task9": "authoredOn", "task10": "authoredOn"}
FORMAT_FAILURES = {"answer written as a sentence", "answer holds objects or lists"}
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
NUMBER_WITH_UNIT = re.compile(r"-?\d+(?:\.\d+)?\s*[A-Za-z%µ][\w/%µ^.-]*")
FHIR = FhirClient()


def newest(mrn: str, code: str) -> tuple[datetime, float] | None:
    url = f"{FHIR_BASE}Observation?patient={mrn}&code={code}&_count=5000&_format=json"
    entries = json.loads(str(FHIR.get(url).data)).get("entry", [])
    found = [
        (datetime.fromisoformat(e["resource"]["effectiveDateTime"]), e["resource"]["valueQuantity"]["value"])
        for e in entries
    ]
    return max(found) if found else None


def accepted_posts(history: list[dict[str, str]]) -> list[dict[str, Any]]:
    posts: list[dict[str, Any]] = []
    for message, reply in zip(history, history[1:], strict=False):
        if message["role"] == "agent" and message["content"].startswith("POST"):
            if "POST request accepted" in reply["content"]:
                try:
                    posts.append(json.loads("\n".join(message["content"].split("\n")[1:])))
                except json.JSONDecodeError:
                    pass
    return posts


def answer_shape(result: str | None) -> str | None:
    """None for a flat JSON list of plain values; otherwise what is wrong with the answer."""
    try:
        value = json.loads(result) if result is not None else None
    except json.JSONDecodeError:
        return "answer is not JSON"
    if not isinstance(value, list):
        return "answer is not a list"
    if any(isinstance(v, dict | list) for v in value):
        return "answer holds objects or lists"
    texts = [v.strip() for v in value if isinstance(v, str)]
    if any(len(t.split()) >= 4 for t in texts):
        return "answer written as a sentence"
    if any(NUMBER.fullmatch(t) or NUMBER_WITH_UNIT.fullmatch(t) for t in texts):
        return "number as text or with a unit"
    return None


def trap_outcome(case: dict[str, Any], posts: list[dict[str, Any]]) -> str | None:
    """How the run handled the task 9 and task 10 readings the instructions leave unstated, when they apply."""
    category = case["id"].split("_")[0]
    if category == "task9" and (k := newest(case["eval_MRN"], "K")) is not None and k[1] >= 3.5:
        kinds = "+".join(sorted(p.get("resourceType", "?") for p in posts))
        return f"task9 normal potassium: {'ordered ' + kinds if posts else 'no order'}"
    if category == "task10" and newest(case["eval_MRN"], "A1C") is None:
        return f"task10 no A1C: {'ordered' if posts else 'no order'}"
    return None


def failure_reasons(case: dict[str, Any], output: dict[str, Any], trap: str | None) -> list[str]:
    """Every observable reason a failed run failed, most specific first."""
    category = case["id"].split("_")[0]
    history, posts = output["history"], accepted_posts(output["history"])
    reasons: list[str] = []
    if category in READ_ONLY and any(m["role"] == "agent" and "POST" in m["content"] for m in history):
        reasons.append("wrote on a read-only task")
    if trap is not None and (trap.startswith("task9 normal potassium: ordered") or trap == "task10 no A1C: no order"):
        reasons.append(trap)
    field = EXACT_TIME_FIELD.get(category)
    if field and any(field in p and p[field] != NOW_TEXT for p in posts):
        reasons.append("timestamp in a write not copied exactly")
    if category in {"task3", "task8"} and not posts:
        reasons.append("required write missing")
    if category not in {"task3", "task8"} and (shape := answer_shape(output["result"])):
        reasons.append(shape)
    searched = [
        re.findall(r"[?&]code=([^&\s]+)", m["content"])
        for m in history
        if m["role"] == "agent" and m["content"].startswith("GET")
    ]
    if category in LAB_CODE and LAB_CODE[category] not in {code for codes in searched for code in codes}:
        reasons.append("never searched the lab code the task names for results")
    if category in LAB_CODE and any(m["role"] == "user" and '"relation": "next"' in m["content"] for m in history):
        reasons.append("read only part of the results (a next page existed)")
    return reasons or ["other: a well-formed answer with the wrong value"]


def replay_finish_check(tasks: list[dict[str, Any]], runs: dict[int, Any], recorded: dict[int, bool]) -> None:
    """Run arm T's finish check over GPT-4.1's final answers: which format failures it catches, and what it costs.

    A nudge on a correct answer costs one round, never the answer, because the next finish is accepted as it stands.
    """
    caught = missed = nudged_correct = 0
    for i, case in enumerate(tasks):
        try:
            answer = json.loads(runs[i]["result"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(answer, list):
            continue
        flagged = bool(answer_problems(answer))
        graded_answer = case["id"].split("_")[0] not in {"task3", "task8"}
        if not recorded[i] and graded_answer and answer_shape(runs[i]["result"]) in FORMAT_FAILURES:
            caught += flagged
            missed += not flagged
        elif recorded[i]:
            nudged_correct += flagged
    print(
        f"finish check replay: catches {caught} of {caught + missed} format failures; "
        f"would also nudge {nudged_correct} of {sum(recorded.values())} correct answers (one extra round each)"
    )


def main(runs_dir: Path) -> None:
    tasks = load_tasks()
    runs = {r["index"]: r["output"] for r in map(json.loads, (runs_dir / "runs.jsonl").read_text().splitlines())}
    overall = json.loads((runs_dir / "overall.json").read_text())
    recorded = {r["index"]: r["status"] == "completedCorrect" for r in overall["custom"]["raw_results"]}
    assert len(runs) == len(tasks) == len(recorded) == 300
    assert all(case["instruction"].strip()[:60] in runs[i]["history"][0]["content"] for i, case in enumerate(tasks))
    print("record index = task position: verified (each task's instruction is in its run's first message)")
    print("recorded statuses:", dict(Counter(r["status"] for r in overall["custom"]["raw_results"])))
    rate = overall["custom"]["success rate"]
    print(f"recorded success {sum(recorded.values())}/300; overall.json success rate {rate}")

    ours = {
        i: grade(case, TaskResult(history=runs[i]["history"], status=Status.COMPLETED, result=runs[i]["result"]))
        for i, case in enumerate(tasks)
    }
    disagree = [(tasks[i]["id"], recorded[i], ours[i]) for i in range(300) if ours[i] != recorded[i]]
    print(f"medgate grade() agrees on {300 - len(disagree)}/300; disagreements (task, recorded, ours): {disagree}")

    per_category: dict[str, list[bool]] = defaultdict(list)
    first_reason: Counter[str] = Counter()
    all_reasons: Counter[str] = Counter()
    traps: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for i, case in enumerate(tasks):
        per_category[case["id"].split("_")[0]].append(recorded[i])
        trap = trap_outcome(case, accepted_posts(runs[i]["history"]))
        if trap:
            traps[f"{trap} -> {'correct' if recorded[i] else 'wrong'}"] += 1
        if not recorded[i]:
            reasons = failure_reasons(case, runs[i], trap)
            first_reason[reasons[0]] += 1
            all_reasons.update(reasons)
            examples[reasons[0]].append(case["id"])
    ordered = sorted(per_category.items(), key=lambda kv: int(kv[0][4:]))
    print("per category:", {category: f"{sum(v)}/{len(v)}" for category, v in ordered})
    print("failures by first reason:", dict(first_reason.most_common()))
    print("all failure reasons:", dict(all_reasons.most_common()))
    print("first examples:", {k: v[:5] for k, v in examples.items()})
    print("trap behaviour:", dict(sorted(traps.items())))
    replay_finish_check(tasks, runs, recorded)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
