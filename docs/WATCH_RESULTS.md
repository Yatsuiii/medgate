# Watch run results

Run 2026-10-22 under docs/WATCH_RUN_PREREG.md (frozen before any model run of the watch; sha256 in NOTES.md). Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b`) on Nebius Token Factory, arm TG (payload gate and evidence gate on), temperature 1.0, top_p 0.95, max_tokens 8192. The ward is demo/ward.json: 7 benchmark patients, potassium and magnesium protocols, 12 new results. Output: `runs/watch_TG.jsonl`. Report: `uv run python -I analysis/watch_run.py --out runs/watch_TG.jsonl --summary-only`.

## Result against the pre-registered criteria

| criterion | result | bar |
|---|---|---|
| graded runs correct (9 events with a benchmark case, 3 runs each) | **23 of 27** | supports at 22 or more, fails at 13 or fewer |
| orders on the must-order-nothing runs (3 events, 3 runs each, includes the eGFR hold) | **0 of 9** | supports needs 0 |
| every drafted order cites its triggering result | **yes** | supports needs yes |
| not completed, gate rejections, format retries | 0, 0, 0 | not a criterion |

By the pre-registered criteria: **supports the product claim, narrowly** (23 against a bar of 22). With 27 runs a 95% interval is about plus or minus 15 points, so this is a go or no-go on a pilot, not a measured accuracy.

| event | correct | orders drafted per run |
|---|---|---|
| S6550627 K 3.1 (low, 2 orders expected) | 1 of 3 | 0, 0, 2 |
| S3084624 MG 1.8 | 2 of 3 | 0, 1, 1 |
| S6542579 MG 1.9 (boundary value) | 2 of 3 | 1, 1, 1 |
| the 6 other graded events | 18 of 18 | as expected |
| the 3 must-order-nothing events | 9 of 9 nothing ordered | 0 |

## Defect in the run script, disclosed

The script did not save transcripts, so the 4 incorrect runs above cannot be read. The verdict does not depend on it. A separate diagnostic (not part of the criteria) re-sampled only the three events that failed, 8 runs each, with transcripts saved: `runs/watch_diag.jsonl`.

| event | diagnostic correct (of 8) | all 11 runs of this event |
|---|---|---|
| S6550627 K 3.1 | 5 | 6 of 11 |
| S6542579 MG 1.9 | 5 | 7 of 11 |
| S3084624 MG 1.8 | 8 | 10 of 11 |

The diagnostic was chosen because those events had failed, so its rates are not an unbiased estimate and are not mixed into the verdict.

## Why the 6 diagnostic failures failed

Three independent readers per run (protocol text, live record, transcript), unanimous on all six. None opened the grader.

| class | runs | what happened |
|---|---|---|
| 4 Condition, **missed order** | 3 | K 3.1: no plan, no reads, `finish` straight away, no order. MG 1.9 twice: the agent looked up the eGFR (133, so no exclusion applies), then finished without ordering. 1.9 is the top of the 1.5 to 1.9 band, and it treated it as outside. |
| 4 Condition, **incomplete order set** | 1 | K 3.1: the oral potassium was ordered, the paired stat potassium level was never created. |
| 5 Payload | 2 | K 3.1: both writes had wrong times (`authoredOn` malformed as `2023-11-11-13T10:15:00+00:00`, and the next-morning draw dated the same day). MG 1.9: the dose was right but the duration as a rate in hours was left out. |

## What this shows and does not show

- **The dominant failure is a silent miss.** In 4 of the 6 diagnostic failures, and in 3 of the 4 original failures, the agent drafted nothing or only part of what the protocol calls for. The agent also wrote no plan in these runs, though the prompt asks for one. A missing order does not appear on the worklist, and an event with no order reads like a legitimate "nothing to do". That is exactly the harm the watch exists to remove, and the clinician's review of drafted orders cannot catch it. The page does show the triggering value beside "No order drafted", which a person scanning could notice, but that is not a guarantee.
- **The gates did not help here.** The payload and evidence gates are structural. They had nothing to check in a run that wrote nothing, and they do not see time fields or a missing duration (docs/GATE_CATCH.md predicted this: meaning errors pass).
- **The flagship demo event is the least reliable one** (K 3.1 is correct in 6 of 11 runs). A live demo on it could miss.
- **Not tested:** whether an enforced plan step, a protocol-completeness check or a different prompt fixes the misses. Any such change is a post-hoc fix to a found problem and has to be tested on events that were not used to find it.
- **Same limits as everywhere:** synthetic patients, two short protocols with one invented exclusion, one model, no clinicians, and no test of the claimed advantage over order sets.

## Cost

The whole of today's model use (pilot, watch run, diagnostic) cost $0.33 on Nebius, absorbed by the $1.00 trial credit. The $59.00 balance was not touched (console, 2026-10-22).

## Update (2026-10-22, later the same day)

The silent misses described above were tested for a fix on held-out events: docs/HELDOUT_RESULTS.md. A one-time review of the agent's decision before it finishes took them from 33 of 120 runs to 0, without false orders, and it is now the watch's default. The measurements in this file are of the earlier configuration (arm TG without the review) and stand as they were.
