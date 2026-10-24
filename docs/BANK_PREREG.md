# Final test on three untouched protocols

**Status: FROZEN 2026-10-24 before any model run on these protocols.** The sha256 of this file goes into NOTES.md first. A later change is a dated deviation note.

## Question

docs/RULESET_RESULTS.md showed a coded rule beats the agent on accuracy for the protocols it was tuned on, and docs/THIRD_PROTOCOL_RESULTS.md showed the agent at 80% on a new protocol. The product claim left standing is: **a unit can add a protocol as plain text and get correct drafts with no code, with a person approving each.** Two fixes made since, found on four DEV protocols (sodium, glucose, thyroid screen, hemoglobin; docs in NOTES.md), are generic: the watch's order tool can carry frequency and duration, and a "checked" configuration (field-by-field review, ISO time gate). Does the claim hold on three protocols that played no part in finding or building the fixes?

## Fixed design

- **TEST protocols:** creatinine rise (trend rule, two service orders, hold on no previous value), INR (tiered vitamin K, oral and IV, relative-time recheck, platelet hold) and LDL-slot oral metformin by glucose tier (ALT hold), as in analysis/protocols/p_creatinine.py, p_inr.py, p_ldl.py. I read their texts before the fixes were built; the fixes are generic and were chosen from DEV results only. Module sha256 (first 16): p_creatinine 5ab5988d823d5bcd, p_inr 116b1e76012755a4, p_ldl 9de129ea4866efde (p_inr changed once after the split, to accept an IV duration written as the order's own duration, a judge bug class found on DEV; disclosed in NOTES.md).
- **Wards** (`runs/bank/*_ward.json`, built by `bank_run.py ward` before the run): creatinine 46 events (7 need orders, 27 hold, 12 none), inr 20 (7, 1, 12), ldl 32 (18, 2, 12). sha256: 69af4a541ae1ce77, 4f8c7c447431b687, 21341cfea308ab42. Runs per event: 8 need orders, 4 hold, 3 need nothing: 484 runs per arm.
- **Arms**, same events, same sampling (nvidia/nemotron-3-super-120b-a12b on Nebius, temperature 1.0, top_p 0.95, max_tokens 8192): **watch** (gates.WATCH, the product as it stood after the order tool gained timing) and **checked** (gates.WATCH_CHECKED). Code frozen at: tool_agent.py 35e6a7dc9121a444, gates.py 7d7cc3a841bda33e, tasks.py 315c1dff16d39c8d, bank_run.py 841db0c9df94ed93.
- **Scored set:** the orders a clinician could approve: accepted by the gates and not superseded. The count dropped from the raw drafts is reported.
- **Baseline:** each protocol's hand-coded rule script, scored by the same judge (expected 100%).
- **No edit to src/, to the protocol modules or to the judges between this freeze and the report.** A bug found in a judge after the run is reported as found and the run is rescored only in a clearly labelled second table.

## Metrics, per arm

End to end = complete and accurate among the runs on events that need orders (a miss, an incomplete set or a wrong payload counts as a failure); pooled over the three protocols and per protocol. Also: misses, orders on hold events (hold runs: 120), false orders on need-nothing events (none runs: 108), model calls per run.

## Criteria, fixed before any output

For the arm called **checked**:

- **The claim is SUPPORTED** if all hold: pooled end to end at least 90%; every protocol at least 80%; orders on at most 6 of 120 hold runs; at most 2 false orders in 108 none runs.
- **It FAILS** if pooled end to end is below 85%, or orders on hold runs exceed 12.
- Anything else is CAUTION.
- **The fixes are credited** only if checked beats watch by at least 3 points pooled end to end with hold orders and false orders no higher by more than 3 combined. Otherwise they are reported as not shown to help.
- The rule script is not a pass bar: it is the reference. Where the agent is below it, the gap is the cost of writing no code.

## What will not be concluded

Nothing about real hospitals, clinicians, other models or protocols outside these three. Three protocols are three data points: a pass says this agent handled these texts, not that it handles any.
