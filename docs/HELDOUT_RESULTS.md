# Held-out result: the finish-time review

Run 2026-10-22 under docs/HELDOUT_PREREG.md and docs/HELDOUT_ADDENDUM.md (both frozen before any run on this set; sha256 in NOTES.md). Nemotron 3 Super on Nebius, arm TG (the baseline) against arm TG plus the finish-time review (`gates.WATCH`), the same 44 held-out events from 27 patients that were never on the demo ward, same sampling, run side by side. 10 runs per event that needs orders or a hold, 4 per event that needs nothing: 254 runs per arm. Files: `runs/heldout_baseline.jsonl`, `runs/heldout_audit.jsonl`. Report: `uv run python -I analysis/heldout_run.py compare runs/heldout_baseline.jsonl runs/heldout_audit.jsonl`.

## Result against the pre-registered criteria: the change works

| | baseline | with the review |
|---|---|---|
| silent misses, 120 runs on the 12 events that need orders | **33 (27.5%)** | **0** |
| runs with a complete order set | 87 | 120 |
| orders accurate (code, route, dose, duration or time), of runs with a complete set | 74 of 87 | 108 of 120 |
| end to end: complete and accurate, of 120 | 74 (62%) | 108 (90%) |
| false orders, 134 runs on events that need nothing or a hold | 0 | 0 |
| orders drafted on the event that should be held (10 runs) | 0 | 0 |
| runs that did not finish | 0 | 0 |
| model calls per run | 1.98 | 3.27 |
| format retries (prose-only replies) | 2 | 18 |

- The pre-registered verdict is **THE CHANGE WORKS**: misses at most half the baseline's (0 against 33), false orders at most the baseline's plus 3 (0 against 0), payload accuracy not lower, incomplete sets not higher, nothing ordered on the hold event, no unfinished runs.
- Every one of the 12 events improved (baseline misses 1 to 5 of 10 per event, review 0 of 10). The two potassium events went from 7 misses in 20 runs to 0. Fisher exact one-sided p = 9e-12 on the 33 against 0, treating runs as independent, which they are not entirely (12 events).
- **Rubber-stamp check: passed.** In 28 of the 120 runs the agent had drafted no order when the review arrived; all 28 drafted one after it. In 134 of 134 runs that needed nothing, it wrote nothing after the review. 5 runs that were already complete wrote more after it (see below).

## A side effect the criteria did not measure

In **7 of 120** runs that need orders (5.8%) the review arm drafted **more** orders than needed, against 0 in the baseline: 2 or 3 in most, 5 magnesium orders in one run. They are mostly not copies. When the review led the agent to fix something, it created a new order, because there is no amend tool, and left the first one in place (the pairs differ in the dosage, the cited result or the time). A reviewer shown both cards could approve both. The pre-registered metrics count a run with more orders than needed as complete, so this is not in the verdict above. It is handled in the next step (a "superseded" mark on the earlier order) and its effect is evaluated offline on these saved runs.

## What this does and does not show

- On this model, protocol shape and wording, a one-time review before finishing removed the silent misses on events not used to find the problem, without prompting false orders. The wording was written after the failure classes were known; the held-out events are what support the claim.
- **Accuracy is not fixed:** 12 of 120 runs with a complete set still have a wrong dose, duration or time (90% accurate). The review raised end-to-end correctness from 62% to 90%, mostly by removing misses.
- The cost is about 1.3 more model calls per run and more prose-only replies. Latency per event roughly doubles.
- Same limits as everywhere: synthetic patients, two short protocols, one model, 12 events that need orders. It says nothing about real hospitals or other models.
