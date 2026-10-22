# Addendum 1 to docs/HELDOUT_PREREG.md

**Written 2026-10-22, after the fix was chosen and built and before any model run on the held-out set** (the baseline and the treatment have both not run). docs/HELDOUT_PREREG.md is unchanged; its sha256 is in NOTES.md. This file's sha256 goes into NOTES.md before the first run.

## The treatment

A finish-time review, chosen by a design review (three independent designs, each attacked by a critic, then a decision) and built as `GateConfig.finish_review` (preset `gates.WATCH` = arm TG plus the review). The first accepted finish is answered with the review text and the orders created so far, and the next finish is accepted as it stands. The review is not a format retry and adds 3 to the round limit. It names no drug, number or order type, never says that an order is missing, and is the same for every event. The agent runs with it only in the held-out experiment; the screen's default is unchanged until the experiment passes.

- sha256 of the review text (`medgate.tool_agent.REVIEW`): `c51a6b3ebce0406d34c49d677f386629885e82d96c4df4376245ee8661e979b1`
- sha256 of the held-out ward file (`runs/heldout_ward.json`): `9a8c64aeb5a7d47ea83ed180b2f4cbd9314fed7e4382baad1e1b7d02009dd56c`
- The wording was written after the three failure classes were known, so only the held-out result can support any claim. The three diagnostic events are not used for the verdict.

## Design changes (before any run on this set)

- **Runs:** 10 per event that needs orders or a hold (13 events, 130 runs per arm), 4 per event that needs nothing (31 events, 124 runs per arm), same events in both arms, run side by side in one session. This replaces the "5 runs per event" of the main file, for power.
- **Extension rule:** unchanged, but on the pooled counts: if the baseline has fewer than 6 silent misses per 60 runs on needs-orders events (12 per 120), the held-out set did not reproduce the problem and the result is INCONCLUSIVE.

## Added criteria (stricter than the main file, never looser)

- **The change fails** (in addition to the main file's conditions) if the treatment drafts **any** order on the event that should be held (eGFR below 45), or if the treatment has more runs that do not finish (round limit or invalid) than the baseline.
- **Rubber-stamp check, reported and decisive for the next step, not for the verdict:** among treatment runs that drafted no order before the review message, the share that drafted an order after it. If it is under a quarter, a second look by the same model does not work, and the next experiment is independent attempts with a per-order merge, not more review wording.
- **Reported, not criteria:** runs where the review changed the outcome; runs where the review reply carried text versus a bare second finish; model calls per run; the Nebius cost.

## Post-hoc readout (labelled, not used for the verdict)

After the main result, the three diagnostic events (S6550627 K, S6542579 MG, S3084624 MG) may be run in both arms, 20 runs each, to see whether the pattern seen in the diagnostic is reproduced.
