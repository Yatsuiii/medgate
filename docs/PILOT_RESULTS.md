# Pilot results

Run 2026-10-22 under the protocol frozen in docs/PILOT_PREREG.md (sha256 in NOTES.md, file unchanged), with one dated deviation: the endpoint was Nebius Token Factory, not the NVIDIA API (NOTES.md, Deviation 1). Model `nvidia/nemotron-3-super-120b-a12b`, temperature 1.0, top_p 0.95, max_tokens 8192, one run per task, graded by the benchmark's own grader. Run files: `runs/pilot_A.jsonl`, `runs/pilot_T.jsonl`. Report command: `uv run medgate pilot runs/pilot_A.jsonl runs/pilot_T.jsonl`.

## Result

| category | A (reference loop) | T (tool agent) |
|---|---|---|
| task1 | 3/3 | 2/3 |
| task2 | 3/3 | 3/3 |
| task3 | 1/3 | 2/3 |
| task4 | 2/3 | 3/3 |
| task5 | 1/3 | 3/3 |
| task6 | 1/3 | 2/3 |
| task7 | 0/3 | 3/3 |
| task8 | 1/3 | 3/3 |
| task9 | 0/3 | 3/3 |
| task10 | 1/3 | 3/3 |
| **all 30** | **13** | **27** |

- Paired: only T correct on 15 tasks, only A correct on 1. McNemar exact p = 0.0005. With 30 tasks a 95% interval is about plus or minus 17 points.
- Neither arm wrote on a read-only task, and no write was rejected by a gate (arm T runs with the format retry only). A hit the round limit on 3 tasks, T on none. T had 4 format retries.
- One of T's 27 correct runs (task1_13) is the smoke run that preceded the pilot, used once and not repeated (NOTES.md).

## The pre-registered decision

T got 27 of 30, which is the "27 or more" line: little room for gates. The story is open-model parity, and gate claims are dropped. Applied as written, on the boundary, so it does not depend on how the failures are classified. The thesis "mechanical gates raise task success on top of a strong harness" is dropped by its own pre-registered rule.

What this does not show (also from the pre-registration): nothing about parity with GPT-4.1's published 91.0%, because the harness is different and there are only 30 tasks.

What it does show, with the 30-task caveat: the same model went from 13 to 27 correct when only the harness changed (native tool calls, every search match shown newest first, a calculator, a finish check). The harness matters more than anything the gates were meant to add.

## T's three failures, classified

Three independent readers per failure (one looking at the task text, one checking the live record, one following the transcript), then a vote. No reader opened the grader.

| task | class | readers | what happened |
|---|---|---|---|
| task1_25 | 2 Retrieval | 3 of 3 | The agent put the full name "Russell Shields" in the `given` field, got 0 results, ignored the empty-search hint and finished "Patient not found" without retrying. |
| task3_16 | 5 Payload | 3 of 3 | The vitals write used `subject.reference` = `S6192632`, a bare MRN, instead of `Patient/S6192632`. Everything else was right. The harness accepted it silently. |
| task6_12 | 2 Retrieval | 2 of 3 (the third said Other: no agent error) | The 24-hour average needed 4 results (mean 188); the search returned 2 (mean 204). See below. |

## Two harness findings

- **The FHIR server's date filter drops in-window records when the time carries an offset.** For patient S6222362, `date=ge2023-11-12T10:15:00+00:00` returns 2 observations, and `date=ge2023-11-12T10:15:00` returns all 4. medgate encodes the `+` correctly (`%2B`), so the cause is the server, not the encoding. Our agent trusted the server-side filter. Applying the window ourselves, on each result's own clinical time as `medgate.results` already does for ordering, would have fixed this run. Not changed: the pilot is frozen. Any change is a dated post-pilot deviation and must be tested on tasks that were not used to find it.
- **The existing gates would not have caught task3_16's malformed reference.** Replaying the actual write through the gates (both arm T's and TG's) finds no problem: the bare MRN passes the spec check and the evidence check. A check that a reference has the form `ResourceType/id` would catch it. That is a structural check, in the same family as the ones docs/GATE_CATCH.md shows the gates already make, and it is not built.

## What this changes

- The success-gain claim for the gates is dropped. The gates' remaining value is the safety framing, measured only with hand-made mistakes (docs/GATE_CATCH.md), not with model behavior.
- Two of three failures are retrieval, one is a payload shape. None is a "wrong patient" or "uncited order" mistake, so this pilot gives no evidence that the evidence gate would fire on a real model.
- The pilot measured the benchmark's tasks. It did not measure the results watch (protocol application, exclusions, citations) on a model. That is the open question for the product, and it is what to run next.
