# Separate-model verifier: replay on saved order sets

**Status: FROZEN 2026-10-24 before any verifier call.** The sha256 of this file goes into NOTES.md first.

## Question

Today the agent that drafts an order set also reviews it (the finish-time review). Would a second model, shown only the protocol text, the raw record values and the drafted orders, catch the sets that are wrong or incomplete, without flagging the correct ones? That would be a role split inside the Nemotron family (drafter, independent checker) instead of one model checking itself.

## Fixed design

- **Data:** the saved runs of the second confirmation (`runs/bank/{sodium_high,phosphate_oral,lab_pair_urgent}_confirm2_watch.jsonl`, 600 runs, judges unchanged). Each run's final order set is rebuilt from its transcript with the same proposal logic as the runner (`analysis/confirm3_rescore.py`, validated there).
- **Ground truth:** the protocol's own judge verdict. FAILING = a need-order run that was a miss, incomplete, or complete but judged inaccurate (33 runs). CORRECT = a complete accurate set (407 runs) or an empty set on a hold or no-order event.
- **Sample (seed 0):** all 33 failing sets, 60 correct complete sets, 20 correct empty sets on hold or no-order events (113 in all). The sampled ids are written to `runs/verifier/sample.json` before any call.
- **Verifier input:** the protocol text; the ward time; raw record values only (the trigger result and, where the protocol has an exclusion, creatinine, eGFR or platelets); the drafted orders as JSON, or "no orders drafted". It never sees the expected dose, tier, count, the judge, or whether the run failed. Caveat: the record values come from the oracle's own record lookup, not from the agent's trace.
- **Verifier output:** one JSON object, verdict `ok` or `problem`, plus a one-sentence reason. Temperature 0, max_tokens 2000.
- **Models:** Super 120B first (`nvidia/nemotron-3-super-120b-a12b`). Ultra (`nvidia/Nemotron-3-Ultra-550b-a55b`) on the same sample only if, after the Super run, the Super tokens measured suggest the Ultra run costs under \$1 at a price the user reads from the console; otherwise not run.
- **Spend cap:** about \$1 in total for this test.

## Criteria, fixed before any output

- **USEFUL AS A SECOND REVIEWER** if recall on the 33 failing sets is at least 70% AND the false alarm rate on the 80 correct sets is at most 10%.
- **NOT SHOWN TO HELP** otherwise. Either way report recall and false alarms per failure type (miss, incomplete, wrong field) and the reasons it gave for the sets it missed.
- No claim about the verifier lowering the drafted error rate: this replay does not feed the verifier's finding back to the drafter. It measures detection only.

## What will not be concluded

Nothing about other protocols, other prompts, or a closed loop where the drafter fixes what the verifier flags (not tested). The sample is 113 sets from three protocols and one batch of runs. The judge is the ground truth, and the judges are model-written and unaudited.
