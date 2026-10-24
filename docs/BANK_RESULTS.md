# Final test on three untouched protocols

Run 2026-10-23 under docs/BANK_PREREG.md (frozen first; sha256 in NOTES.md). Nemotron 3 Super on Nebius, two arms on the same 98 events (484 runs each): **watch** (gates.WATCH) and **checked** (gates.WATCH_CHECKED: field-by-field review and an ISO time gate). Protocols: creatinine rise, INR, LDL-slot oral metformin. Files `runs/bank/{creatinine,inr,ldl}_final_{watch,checked}.jsonl`, follow-up `runs/bank/ldl_final2_*.jsonl`. Report: `uv run python -I analysis/bank_run.py report FILE...`.

## Result against the frozen criteria: the claim FAILS as run

| end to end (complete and accurate), runs on events that need orders | watch | checked |
|---|---|---|
| creatinine | 56 of 56 | 56 of 56 |
| inr | 54 of 56 | 50 of 56 |
| ldl | **0 of 144** | **4 of 144** |
| **pooled** | **110 of 256 (43%)** | **110 of 256 (43%)** |
| orders on hold events (120 runs) | 0 | 1 |
| false orders on need-nothing events (108 runs) | 0 | 0 |
| silent misses | 1 | 2 |
| model calls per run | 4.13 | 4.11 |

The frozen bar was 90% pooled to support the claim and 85% as the floor below which it fails. Both arms are far below it, so by the rule written first the answer is **FAILS**. The fixes made on the dev protocols are **not credited**: checked equals watch pooled and is worse on INR (50 against 54).

## Why LDL collapsed (found on the test, not a model failure)

The LDL protocol says the metformin order has "priority routine". The order tool the agent writes with (the benchmark's MedicationRequest) has no `priority` field; only ServiceRequest does. The agent followed its tool, so it left priority out, and the judge, which requires it, marked every order wrong. In 4 runs of the checked arm the field-by-field review made the agent add it anyway. Everything else in those orders (drug, route, dose, once daily for 3 days) was what the judge looks for, which the follow-up below confirms. This is the same kind of defect the dev protocols had (no frequency or duration field) and it is a real product gap: a drug order cannot carry its priority.

## Follow-up after a generic fix (post-hoc, not a clean test)

The watch's medication tool now has the standard FHIR priority field (tasks.watch_functions; benchmark arms unchanged). LDL was re-run alone, fresh, for both arms, judge unchanged.

| | watch | checked |
|---|---|---|
| ldl, end to end | **144 of 144** | **144 of 144** |
| ldl, false orders / hold orders | 0 | 0 |
| pooled with the frozen creatinine and INR runs | **254 of 256 (99%)** | **250 of 256 (98%)** |

By the numbers this clears the original bars, but it cannot be claimed as the pre-registered result: the defect was found by looking at the test, and the fix was made after. A clean confirmation needs a protocol that no one has looked at.

## What this shows and does not show

- **Original claim ("add a protocol as text, no code"):** on these three protocols it held up once the order tool could express the orders: 98% to 99% of runs on events that need orders were correct and complete, with 0 or 1 orders on 120 hold runs and 0 false orders on 108 normal ones. A coded rule is still 100%, so the cost of writing no code is roughly 1 to 2 runs in 100 wrong, and a person still approves each.
- **The quality of the tool matters more than the prompt:** both sets of failures (dev sodium and this LDL) came from the order form not being able to carry what a normal protocol says (frequency, duration, priority). The prompt changes (field check, time gate) added little: they helped on glucose (62 against 43 of 80 on dev) and did not help on these three.
- **Judge risk:** three judge or tool bugs surfaced across dev and test, each found after running. Judges for any new protocol should be run on payloads in the shape the tool produces before the model run.
- **Limits:** three protocols and 98 events, one model, synthetic data, invented identifiers, no clinician. The protocols were designed by model agents and reviewed by other model agents, not by a clinician. The test texts were read by me before the dev fixes (the fixes were generic and chosen from dev results).

## Cost

About 2,500 model runs across the bank, the calcium test and the dev iterations, a few dollars of the Nebius credit.
