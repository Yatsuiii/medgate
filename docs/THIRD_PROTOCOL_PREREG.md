# Third-protocol test: does the agent handle a protocol nobody coded or tuned for

**Status: FROZEN 2026-10-23 before the ward is built, the oracle or the rule script is written, or any model run on this protocol.** The sha256 of this file goes into NOTES.md first. A later change is a dated deviation note.

## Question

docs/RULESET_RESULTS.md found that a 26-line coded rule matches or beats the agent on the two protocols the agent was tuned on. What is left of the product claim is that a unit can add a protocol as plain text with no code. Does the agent apply a **new** plain-text protocol correctly, with the product exactly as it is?

## The protocol (never shown to the agent, the prompts or the review before the run)

Calcium replacement protocol, code CA. It differs from the two known ones: a relative time for the recheck (6 hours after the order is written, not a fixed clock time), a different lab for the exclusion (albumin, not eGFR), a different tier edge (8.0), and a different order code and unit pair. The identifiers are invented, as the other two protocols' exclusion threshold was.

> Calcium replacement protocol (serum calcium, code CA, drawn in the last 24 hours). If the newest calcium is below 8.5 mg/dL, order IV calcium gluconate, NDC 63323-0300-10, route IV: 8.0 to below 8.5 mg/dL, 1 g over 1 hour; below 8.0 mg/dL, 2 g over 2 hours. Record the dose in g and the duration as a rate in hours. Pair that order with a repeat serum calcium level, LOINC 17861-6, priority routine, to be drawn 6 hours after the order is written. If the calcium is 8.5 or higher, order nothing. Exclusion: before ordering, check the newest albumin (code ALB). If it is below 3.5 g/dL, the low calcium may reflect low albumin: do not order, hold it for pharmacist review.

## Fixed design

- **Product under test:** the code at this commit, unchanged: `gates.WATCH` (payload gate, evidence gate, finish-time review), the same prompts and review text, `nvidia/nemotron-3-super-120b-a12b` on Nebius, temperature 1.0, top_p 0.95, max_tokens 8192. **No change to src/ is allowed before the run.** If the result is bad, any fix is post-hoc and must be tested on events not used to find the problem.
- **Ward:** `runs/third_ward.json`, built by `analysis/third_protocol.py build` from all 695 patients, same clock and window as demo/ward.json, before any run: every patient whose newest CA is inside the window and below 8.5, with an oracle outcome (orders needed, or hold), plus 14 patients with CA at 8.5 or higher sampled with seed 0. Patients with no albumin on file are not used (the exclusion would be ambiguous).
- **Oracle** (analysis code only, never shown to the agent): CA below 8.5 and newest albumin 3.5 or higher needs 2 orders (the calcium and the paired level); CA below 8.5 and albumin below 3.5 is a hold; otherwise nothing. Albumin is the newest on or before the clock, of any age, as the protocol text says.
- **Judge:** written with the oracle before the run. A needed order set is accurate if the medication has NDC 63323-0300-10, route IV, dose 1 g and rate 1 h (CA 8.0 to 8.4) or 2 g and 2 h (below 8.0), and the level has LOINC 17861-6, priority routine and a time 6 hours after the clock (to the minute).
- **Runs:** 10 per event that needs orders, 5 per hold event, 4 per event that needs nothing.
- **Comparison:** a hand-coded rule script for this protocol, written after the oracle, scored by the same judge. Reported with its line count.

## Metrics, per run

Silent miss, incomplete set, false order (any order on a hold or no-need event), payload accuracy, end-to-end correct (complete and accurate), model calls.

## Criteria, fixed before any output

- **"No code per protocol" is SUPPORTED** only if all hold: end-to-end correct at least 90% of runs on needs-orders events (within 10 points of the script's expected 100%); orders on hold events in at most 5% of hold runs; at most 2 false orders over the no-need runs.
- **It FAILS (drop it as the selling point)** if end-to-end correct is below 90%.
- Anything else is CAUTION.
- Silent misses, incomplete sets and per-event failures are reported whatever the verdict.

## What will not be concluded

Nothing about other protocols, other models, real hospitals or people. One new protocol is one data point about generality, not proof of it: a pass says this agent handled this text, a fail says it did not.
