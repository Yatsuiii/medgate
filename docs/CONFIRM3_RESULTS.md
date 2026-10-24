# Third clean confirmation: results

Pre-registered in docs/CONFIRM3_PREREG.md (sha256 recorded in NOTES.md before the runs). Code, protocol modules, wards and judges unchanged between freeze and report. Nemotron 3 Super 120B on Nebius, `watch` arm, 380 runs. Numbers VERIFIED. The first launch hung when the laptop slept (9 of 380 rows saved); the runs were killed and relaunched, resuming from the saved rows with sleep blocked. Nothing else changed.

## Verdict as pre-registered: FAILS

| protocol | end to end | misses | incomplete | hold orders | false orders |
|---|---|---|---|---|---|
| two_drugs_one_lab (CO2, oral + IV + recheck) | 49/56 (87.5%) | 1 | 4 | 0/8 | 0/36 |
| clock_time_recheck (CO2, 06:00 recheck) | 0/104 (0%) | 0 | 0 | 0/8 | 0/36 |
| drug_plus_stat_lab (CL) | 79/80 (98.8%) | 0 | 0 | 0/16 | 0/36 |
| **pooled** | **128/240 (53.3%)** | 1 | 4 | **0/32** | **0/108** |

Pooled is below the 85% fail line, and one protocol is below 80%. By the rule written first, this test failed. Nothing is moved.

## Why: a bug in the clock_time_recheck judge (found after the run)

All 104 complete sets had the recheck at exactly `2023-11-14T06:00:00+00:00`, priority routine, the right code, and an oral urgent drug order with the right NDC and dose. The frozen judge rejected every one because it demands an explicit "once" marker (`repeat.count` 1, a once label, or the word "once" in text). The agent left the timing out, as the watch's own order tool says to for a single dose ("Leave it out for a single dose"). A judge that contradicts the tool's contract is a judge bug, not an agent error. 16 further runs wrote "1 per day" with no end date, which is not a single dose and stays wrong.

## Second table: same transcripts, one judge change (post hoc, labelled)

`analysis/confirm3_rescore.py` rebuilds each run's order list from its transcript with the same proposal logic as the runner. Validation: with the frozen judge it reproduces every saved row (0 mismatches). The only change is that a dose with no timing at all counts as a single dose.

| protocol | end to end (corrected judge) |
|---|---|
| two_drugs_one_lab | 49/56 (87.5%) |
| clock_time_recheck | 96/104 (92.3%) |
| drug_plus_stat_lab | 79/80 (98.8%) |
| pooled | 224/240 (93.3%) |

That would meet every SUPPORTED criterion (90% pooled, each at least 80%, hold orders 0 of 32, false orders 0 of 108). It is post hoc: the judge was corrected after seeing the result, so this is not a pass of the pre-registered test.

## What it shows

- The re-review aimed at incomplete sets worked as intended: incomplete or missing sets were 5 of 240 order runs here (2.1%) against 26 of 440 in the second confirmation (5.9%). Dev runs had shown the same direction.
- The agent was accurate where the judges were fair: 224 of 240 corrected, with no order on any hold event and no false order in 140 runs.
- The pattern across the three attempts: each test exposed a defect of the system (88.3%: orders without a route) or of the judge (here). Three attempts and two post-hoc changes make this a forking path, so no single number should be quoted without that history: 88.3% (caution), 92.5% (supported), 53.3% as run and 93.3% corrected (this).
- Still: synthetic data, one model, model-written protocols and judges, invented NDC and LOINC codes, two of three protocols share one lab, no clinician has used it.
