# Separate-model verifier: results

Pre-registered in docs/VERIFIER_PREREG.md (sha256 in NOTES.md before any call). Replay on saved order sets from the second confirmation: 113 sets (33 failing, 60 correct, 20 correct empty on hold or no-order events), sample fixed before any call. Verifier: `nvidia/nemotron-3-super-120b-a12b`, temperature 0, shown only the protocol text, the ward time, raw record values and the drafted orders. Numbers VERIFIED.

## Verdict: USEFUL AS A SECOND REVIEWER (both bars met), detection only

| | caught or flagged | bar |
|---|---|---|
| failing sets caught | 31/33 (94%) | at least 70% |
| correct sets wrongly flagged | 0/80 (0%) | at most 10% |

By type: omitted orders (miss) 5/5, incomplete sets 21/21, complete sets with a wrong or missing field 5/7. Unparsed replies: 0. Cost: 80,384 prompt and 59,981 completion tokens over 113 calls, about \$0.08 at Super's list prices (\$0.30 and \$0.90 per million). Reasons were concrete, for example "missing the required repeat BUN order" and "does not specify the required infusion duration".

## What it shows and does not

- A second model reading only the protocol and the drafted orders found nearly all the omissions the drafting agent missed, and raised no false alarm on 80 correct sets. It is a cheap check: about 1,200 tokens per set.
- The two it missed were complete sets the judge found inaccurate and the verifier read as matching (BUN protocol). Not diagnosed further.
- **Not shown:** that feeding its finding back to the drafter lowers the error rate (a closed loop was not tested), or that it works on other protocols or other models. The record values the verifier saw come from the oracle's own lookup, not the agent's trace, and the ground truth is the model-written judge. Sample: three protocols, one batch of runs.
- Ultra as the verifier (the larger model checking Super's drafts) was in the plan, gated on cost. It has not been run.

## Work saved, from the same saved runs

Of the 407 correct order sets in that batch, a set has a median of 22 filled-in values (mean 25.2; median 11 per order, 2.09 orders per set): codes, dose and unit, route, timing or duration, priority, subject and the citation. That is the amount a clinician does not have to enter. It is a count of values, not a measured time saving.
