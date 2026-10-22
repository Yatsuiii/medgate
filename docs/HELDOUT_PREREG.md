# Held-out test of a fix for silent misses

**Status: FROZEN 2026-10-22 before the baseline run on this set and before the fix is chosen or built.** The sha256 of this file goes into NOTES.md first. After that nothing here changes; a later change is a dated deviation note.

## Question

The watch run (docs/WATCH_RESULTS.md) showed mostly silent misses: the agent finishes without ordering what the protocol calls for. Does a change to the watch reduce them, without causing false orders, on patients that were not used to find the problem?

## Fixed design

- **Held-out ward:** `runs/heldout_ward.json`, built by `analysis/heldout.py build` from the 688 patients not on the demo ward (seed 0), before any run: every patient with an event that needs orders or a hold, plus 14 patients with only normal results. 44 events: **12 need orders** (10 magnesium, five of them at 1.9, and 2 potassium at 3.0), **1 should be held** (eGFR below 45), **31 need nothing**. The oracle (`analysis/heldout.py`) applies the written protocol rules to the record: potassium below 3.5 needs 2 orders (oral potassium and the paired stat level); magnesium at or below 1.9 needs 1 order unless the newest eGFR is below 45, in which case it is held. Events whose eGFR is missing are not used. The oracle lives in analysis code only; the agent never sees it.
- **Model and settings:** `nvidia/nemotron-3-super-120b-a12b` on Nebius, temperature 1.0, top_p 0.95, max_tokens 8192, as in the pilot and the watch run. Arm TG (payload and evidence gates on).
- **Arms:** **baseline** = the watch exactly as in docs/WATCH_RUN_PREREG.md (the code as of the watch run). **treatment** = baseline plus one change, chosen by a design review and described in a short addendum to this file (a dated note, written before the treatment is run). The change may not add clinical thresholds or protocol logic to code.
- **Runs:** 5 runs per event, for both arms, on the same events: 220 runs per arm.

## Metrics, per run

- **Silent miss:** an event that needs orders and the run drafted **no** order.
- **Incomplete set:** an event that needs 2 orders and the run drafted only 1.
- **False order:** an event that needs nothing, or should be held, and the run drafted any order.
- **Payload accuracy:** among runs that drafted the needed orders, the share whose orders match the oracle on code, route, dose and duration (magnesium), and dose, route and the stat level's time (potassium).
- **Cost:** model calls per run.

## Criteria, fixed before any output

- **The held-out set must reproduce the problem.** If the baseline has fewer than 6 silent misses over the 60 runs on the 12 needs-orders events, add 5 more runs per needs-orders event for both arms (once, same settings) and pool them; if it still has fewer than 6 misses per 60 runs, the result is **INCONCLUSIVE** (the problem did not show up here) and no claim is made.
- **The change works** only if all of these hold: silent misses with the treatment are at most half the baseline's; false orders with the treatment are at most the baseline's plus 3 (of the 160 runs on needs-nothing and hold events); payload accuracy with the treatment is no more than 5 points below the baseline's; incomplete sets do not rise.
- **The change fails** if silent misses with the treatment exceed 75% of the baseline's, or false orders rise by 8 or more.
- **Anything else is CAUTION**: no claim, look at the failures first.

With 12 events the evidence is small; the criteria are for a go or no-go on whether to keep the change, not for a measured rate.

## What will be reported

Counts for each metric and arm with the events they came from; every failing run's class; the extra model calls the change costs; the Nebius cost. Whatever the result, the change is reported with it. If it works, the watch's measured silent-miss rate with it is a post-hoc improvement tested once on held-out events.

## What will not be concluded

Nothing about real hospitals or clinicians; nothing about other models; nothing about the advantage over order sets.
