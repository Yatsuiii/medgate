# Separate-model verifier: results

Pre-registered in docs/VERIFIER_PREREG.md (sha256 in NOTES.md before any call). Replay on saved order sets from the second confirmation: 113 sets (33 failing, 60 correct, 20 correct empty on hold or no-order events), sample fixed before any call. Verifiers: Super (`nvidia/nemotron-3-super-120b-a12b`) and, run second under a token cap, Ultra (`nvidia/Nemotron-3-Ultra-550b-a55b`); temperature 0, shown only the protocol text, the ward time, raw record values and the drafted orders. Numbers VERIFIED.

## Verdict: USEFUL AS A SECOND REVIEWER (both bars met), detection only

| | Super | Ultra | bar |
|---|---|---|---|
| failing sets caught | 31/33 (94%) | 30/33 (91%) | at least 70% |
| correct sets wrongly flagged | 0/80 (0%) | 0/80 (0%) | at most 10% |
| tokens (prompt / completion) | 80,384 / 59,981 | 80,384 / 65,448 | |
| cost at list or reported price | about \$0.08 (console price, \$0.30 / \$0.90 per M) | about \$0.28 (price UNVERIFIED: a third-party aggregator reports \$1.00 / \$3.00 per M) | |

Both models meet both bars. Ultra caught one fewer than Super; either model caught 31 of 33, and the two sets that both missed are the same two.

By type (Super; Ultra is the same except 4/7 on wrong-field sets): omitted orders (miss) 5/5, incomplete sets 21/21, complete sets with a wrong or missing field 5/7. Unparsed replies: 0. Reasons were concrete, for example "missing the required repeat BUN order" and "does not specify the required infusion duration".

## What it shows and does not

- A second model reading only the protocol and the drafted orders found nearly all the omissions the drafting agent missed, and raised no false alarm on 80 correct sets. It is a cheap check: about 1,200 tokens per set.
- The two sets both models missed (BUN protocol), read by hand afterwards, not measured further: in one (BUN 50, 1000 mL over 8 hours) the agent wrote "once every 8 hours" (a frequency) instead of an infusion duration, a real encoding error the verifier read past; in the other (BUN 77, 1000 mL at 250 mL/h) the rate is equivalent to 4 hours, so the judge may be too strict there and the verifier may have been right.
- **Not shown:** that feeding its finding back to the drafter lowers the error rate (a closed loop was not tested), or that it works on other protocols or other models. The record values the verifier saw come from the oracle's own lookup, not the agent's trace, and the ground truth is the model-written judge. Sample: three protocols, one batch of runs.
- The larger model did not help detection here (30 against 31) and used more completion tokens. Ultra's price is not on the console price page, so its cost is an estimate until the balance is read.

## Work saved, from the same saved runs

Of the 407 correct order sets in that batch, a set has a median of 22 filled-in values (mean 25.2; median 11 per order, 2.09 orders per set): codes, dose and unit, route, timing or duration, priority, subject and the citation. That is the amount a clinician does not have to enter. It is a count of values, not a measured time saving.
