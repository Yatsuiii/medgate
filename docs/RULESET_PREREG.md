# Order-set baseline test

**Status: FROZEN 2026-10-22 before the baseline script is written or run.** The sha256 of this file goes into NOTES.md first. A later change is a dated deviation note.

## Question

The product claim is that a ready-written order, drafted from a plain-text protocol, beats what a unit has today. What a unit has today is a coded order set behind a rule-based alert. Two things can be tested or not:

- **B1, a hand-coded rule script** (the strongest cheap baseline): fixed thresholds in code that draft the same orders from the same record. Testable offline, no model.
- **B2, an order set with an alert** as clinicians use it: the alert fires, a person must notice it, open the set and select the orders. The outcome depends on human response (time to dose, override rates). **Not testable here: no clinicians.** It is reported as UNKNOWN and not simulated.

## Fixed design for B1

- **Events:** the 44 held-out events of docs/HELDOUT_PREREG.md (`runs/heldout_ward.json`), same record, same clock.
- **Script:** `analysis/ruleset_baseline.py`, written once, a plain Python rule per protocol (the two protocols of demo/ward.json). It drafts the orders in the same FHIR form the agent writes. It does not use the model and does not read the oracle's output; the thresholds are those of the protocol text.
- **Judge:** the same `judge()` of analysis/heldout_run.py that scored the agent, so the two are scored identically. Its needs come from the oracle in analysis/heldout.py.
- **Cost measure:** lines of code the script needs per protocol, counted by `wc -l` on the rule functions, reported next to the agent's zero lines per protocol.
- **Compared with:** the agent's recorded held-out result with the review (docs/HELDOUT_RESULTS.md: 108 of 120 end-to-end correct, 0 false orders, 0 misses), 10 runs per event.

## Metrics, per event

Silent miss, incomplete set, false order, payload accuracy, end-to-end correct (complete and accurate), as defined in docs/HELDOUT_PREREG.md.

## Criteria, fixed before any output

- **The script matches or beats the agent** if it has no more misses, false orders or incomplete sets and its end-to-end correct rate is at least the agent's 90%. Then the accuracy argument for the agent is gone, and the only remaining claim is that no code is needed per protocol.
- **The agent beats the script** only if the script's end-to-end rate is more than 5 points below the agent's, or it makes false orders.
- Anything else is CAUTION.
- A note on circularity: the oracle and the script both encode the written rules, so a script that agrees with the oracle shows the rules are easy to code, not that the script is clinically right. This test measures whether the agent adds accuracy over a coded rule. It cannot show the agent is clinically better.

## What will be reported

The script's counts per metric against the agent's, its code size, and the claim that remains. Whatever the result.

## What will not be concluded

Anything about B2 (alert response by people), real hospitals, or protocols other than these two. A third-protocol test (does the agent handle a protocol nobody coded for) is a separate step, only done if this one leaves that as the remaining claim.
