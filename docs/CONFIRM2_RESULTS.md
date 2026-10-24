# Second clean confirmation: results

Pre-registered in docs/CONFIRM2_PREREG.md (sha256 recorded in NOTES.md before the runs). Code, protocol modules, wards and judges unchanged between freeze and report. Nemotron 3 Super 120B on Nebius, `watch` arm, 600 runs. Numbers VERIFIED; judges are model-written and unaudited.

## Verdict: SUPPORTED (all four criteria met)

| protocol | end to end | misses | incomplete | hold orders | false orders |
|---|---|---|---|---|---|
| sodium_high (BUN, IV saline) | 73/88 (83.0%) | 1 | 7 | 0/8 | 0/36 |
| phosphate_oral | 55/56 (98.2%) | 1 | 0 | 0/8 | 0/36 |
| lab_pair_urgent (WBC, labs only) | 279/296 (94.3%) | 3 | 14 | 0/36 | 0/36 |
| **pooled** | **407/440 (92.5%)** | 5 | 21 | **0/52** | **0/108** |

Criteria: pooled at least 90% (92.5%, met); every protocol at least 80% (lowest 83.0%, met); at most 4 of 52 hold runs with orders (0, met); at most 2 of 108 false orders (0, met). Rule scripts: 100% on all three. About 4.2 to 5.1 model calls per run.

## What it shows and does not

- Every failure is an omission: a miss or an incomplete order set (26 of 33 failures). When the agent drafted a complete set, it was accurate in 407 of 414 cases. Nothing ordered on hold or no-order events.
- The weakest protocol (BUN) loses most runs to incomplete sets (7 of 15 failures there), not wrong values. I did not classify these further.
- Pooled rate is weighted toward the WBC protocol (296 of 440 runs); the per-protocol rates are above.
- Disclosure of path: this is the second clean attempt. The first (docs/CONFIRM_RESULTS.md) scored 88.3% (CAUTION). I then made one generic change, required route and dose in the watch's drug order tool, after reading those failures, and re-tested on three protocols that no one had run. The two attempts together are a forking path; a pass on the second does not erase the first.
- Still: synthetic data, one model, model-written protocols and judges, some invented NDC/LOINC codes, BUN-for-saline is clinically a stretch, no clinician has used it, and no comparison with an order set plus alert. A person must still approve each order.
