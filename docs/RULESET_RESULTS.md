# Order-set baseline result (B1: hand-coded rule script)

Run 2026-10-22 under docs/RULESET_PREREG.md (frozen first; sha256 in NOTES.md). `uv run python -I analysis/ruleset_baseline.py runs/heldout_ward.json`: the 44 held-out events, no model, scored by the judge that scored the agent.

| | rule script | agent with the review (docs/HELDOUT_RESULTS.md) |
|---|---|---|
| silent misses, events that need orders (12) | **0** | 0 of 120 runs |
| incomplete sets | 0 | not counted separately |
| orders accurate (code, route, dose, duration or time) | **12 of 12** | 108 of 120 |
| false orders, 32 events that need nothing or a hold | **0** | 0 of 134 runs |
| model calls | 0 | 3.27 per run |
| code needed | 26 lines for both protocols (rule functions only) | 0 lines, protocol text is the input |

## Verdict by the pre-registered criteria: the script matches or beats the agent

The script has no misses, no false orders, no incomplete sets and 100% accuracy against the agent's 90%. **The accuracy argument for the agent does not hold against a coded rule.** The agent was never better than a 26-line script on these two protocols.

## What this does and does not show

- **Circularity (the prereg said so):** the oracle and the script both encode the written rules. The result says these two protocols are easy to code, not that the script is clinically right. It also means the agent's 90% is measured against the same rules it was told in text.
- **What remains of the product claim:** no code per protocol, so a unit could add a protocol by writing it as text. That is UNTESTED here: both protocols were hand-checked and the agent was tuned against them (review wording written after the failures). It needs a protocol that nobody coded or tuned for.
- **Update 2026-10-23:** tested in docs/THIRD_PROTOCOL_RESULTS.md. It failed the pre-registered bar (80% against 90%).
- **B2 (order set with an alert, as people use it): UNKNOWN.** Whether a prefilled draft beats an alert plus an order set depends on how people respond (time to dose, override rates). It needs clinicians. Nothing in this repo measures it, and a rule-script alert would trigger on the same results as the agent.
- Also note: the rule script is deterministic and cannot make the 10% dose/time errors, and it cannot miss. A real build would use it if protocols were fixed.

## Next useful test, if the remaining claim is to be kept

A third protocol in plain text that neither the script nor the agent's prompts were written for, scored by an oracle written before the run (cost: a few cents of model calls and about 30 lines of oracle). Kill condition: if the agent is below the script's accuracy there by more than 10 points, drop "no code per protocol" as the selling point.
