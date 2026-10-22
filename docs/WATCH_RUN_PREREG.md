# Watch run: the results watch on a model

**Status: FROZEN 2026-10-22 before any model run of the watch.** The sha256 of this file goes into NOTES.md first. After that nothing here changes; a later change is a dated deviation note.

## Question

Can Nemotron, behind the gates (arm TG), apply the demo ward's protocols to new results correctly: order what the protocol calls for, cite the triggering result, order nothing when the protocol says not to, and hold when an exclusion applies? This is the product's claim, which the benchmark pilot did not measure (docs/PILOT_RESULTS.md).

## Fixed design

- **Ward:** demo/ward.json (7 benchmark patients, potassium and magnesium protocols, `now` 2023-11-13T10:15:00+00:00, window 24 h) with its 12 new results. The ward and protocols are not edited after this file is frozen.
- **Model and settings:** `nvidia/nemotron-3-super-120b-a12b` on Nebius Token Factory, temperature 1.0, top_p 0.95, max_tokens 8192, as in the pilot. Gates: arm TG (payload gate and evidence gate on). The agent gets the protocol text and the new result exactly as `watch.case_for` builds them.
- **Runs:** 3 independent runs per event, 36 runs in all.
- **Grading, 9 events with a benchmark case** (potassium events belong to task 9, magnesium events to task 5, for the same patient): the benchmark's own grader, against that patient's own case. 27 runs.
- **Checks, 3 events with no benchmark case** (S6542579 K 3.7 and S0636132 K 4.2, both normal; S0722219 MG 1.7 with eGFR 41, which the demo protocol holds): the correct outcome is that nothing is ordered. 9 runs.
- **Citations:** every order drafted must cite the triggering Observation in `reasonReference`. Checked on every run that drafts an order.

## Criteria, fixed before any output

- **Supports the product claim (BUILD continues):** at least 22 of the 27 graded runs correct (80%), and no order drafted on any of the 9 no-order runs, and every drafted order cites its triggering result.
- **Fails (PIVOT or SHELVE the watch for this model):** 13 or fewer of the 27 graded runs correct (50% or under).
- **Between:** CAUTION. Classify the failures (below) before any change.

With 27 runs a 95% interval is wide (about plus or minus 15 points at 80%). The criteria are for a go or no-go on a pilot, not a measured accuracy.

## Failure classes

The 8 classes of docs/PILOT_PREREG.md, plus a 9th for this workflow: **Exclusion missed or invented** (ordered where the protocol's exclusion applies, or held where it does not).

## What will be reported

Counts per criterion, per event and per category; each failing run's class with its evidence; format retries and gate rejections; the Nebius cost of the run (balance before and after).

## What will not be concluded

- Nothing about real hospitals, real protocols or clinicians: the data is synthetic and the protocols are short and written from the benchmark's own wording, with one invented exclusion.
- Nothing about the claimed advantage over protocol order sets (an order arriving ready to sign), which this run does not test.
