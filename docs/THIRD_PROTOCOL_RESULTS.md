# Third-protocol result: a calcium protocol the product was never tuned on

Run 2026-10-23 under docs/THIRD_PROTOCOL_PREREG.md (frozen first; sha256 in NOTES.md). Product unchanged from commit f2b0ccb (`gates.WATCH`), Nemotron 3 Super on Nebius, same sampling. Ward `runs/third_ward.json` (sha256 34b687f5...): 42 events, 8 need orders, 20 should be held (albumin below 3.5), 14 need nothing. 236 runs (10 per needs-orders event, 5 per hold, 4 per need-nothing). Output `runs/third_agent.jsonl`; report `uv run python -I analysis/third_protocol.py report runs/third_agent.jsonl`.

## Result against the pre-registered criteria: FAILS

| | agent | rule script |
|---|---|---|
| silent misses, 80 runs on events that need orders | 1 | 0 of 8 events |
| complete and accurate (end to end), of 80 | **64 (80%)**, bar 90% | 8 of 8 |
| orders on the hold events, 100 runs | 5 (5%), bar at most 5% | 0 |
| false orders, 56 runs on need-nothing events | 0, bar at most 2 | 0 |
| unfinished runs | 0 | n/a |
| model calls per run | 3.94 | 0 |
| code needed | 0 lines | 21 lines (one function) |

By the frozen rule, end-to-end below 90% means **"no code per protocol" FAILS as a selling point**. The other two bars (holds, false orders) were met, the hold one exactly at its limit: 5 of 100 hold runs drafted an order (one each on 5 different patients, 4 clean runs for each).

## What the 16 non-correct runs were (post-hoc reading, not part of the verdict)

- 1 silent miss; 15 runs with a complete set and a wrong payload.
- **9 of the 15 wrote the rate as `1 g/h`** instead of the protocol's wording (g over hours, `rateQuantity` in hours). 1 g/h is the same infusion for every tier of this protocol (1 g over 1 h, 2 g over 2 h), so clinically these are right in a different encoding. The judge was fixed before the run and requires `h`, so they count as wrong in the verdict.
- 2 wrote a wrong duration (2 g given at a rate of 1 h), 3 left the duration out, 1 not diagnosed.
- If the `1 g/h` encoding were accepted, end to end would be 73 of 80 (91%). **That is a post-hoc change to the judge after seeing the output, so it does not change the verdict.** The real floor is 6 to 7 runs in 80 with a clinically wrong or incomplete payload, and the 1 miss.
- The weak events are the two-gram tier (7.1 and 7.4, albumin exactly 3.5 for 7.1): 5 of 10 and 4 of 10 wrong. The 1 g events are 8 to 10 of 10.

## What this does and does not show

- **The claim as stated fails,** by the number I wrote down before: on a protocol nobody tuned for, the agent is 80% accurate end to end against a script's 100%, and a person still has to catch the rest.
- **It is not a collapse.** The agent applied a new protocol from text alone: right drug, route, tier, exclusion (hold) and relative recheck time in most runs, with 1 miss in 80 and 0 false orders on normal results. Most of the gap is one encoding ambiguity that the protocol text leaves open ("duration as a rate in hours").
- **The hold behaviour is borderline:** 5% of hold runs ordered anyway, the one safety-relevant place the agent was not reliable.
- **Limits:** one new protocol, 8 needs-orders events (the 90-run estimate is clustered by event), one model, synthetic data, invented identifiers. The script is 21 lines for this protocol because it is the same shape as the other two.
- **Any fix is post-hoc.** A clearer unit in the protocol text or in the tool schema could close the encoding gap, but it would have to be tested on events and a protocol not used to find it.

## Consequence for the product claim

The plain-text-protocol idea survives only as: the agent drafts correctly most of the time and a clinician must approve. It does not beat a coded rule on accuracy, and it was not shown to remove the need for a coded check. What a unit could still gain is not having to write the rules, at the cost of reading every draft.
