# Clean confirmation on three fresh protocols

**Status: FROZEN 2026-10-23 before any model run on these protocols.** The sha256 of this file goes into NOTES.md first. A later change is a dated deviation note.

## Why

docs/BANK_RESULTS.md: the frozen final test FAILED as run (43%) and the 254/256 follow-up was post-hoc, so it is not a clean pass. The failure was an order tool with no priority field; that and the timing fields are now in `watch_functions()`. This test asks whether the claim holds, with code frozen first, on protocols that no one has run or tuned against.

Claim: a unit can add a protocol as plain text and get correct drafts with no code, a person approving each.

## Fixed design

- **Protocols** (analysis/protocols/), each written by a separate agent that had not seen any run output, with its own oracle, judge and rule script: potassium_iv (IV or oral KCl by level, recheck at +6 h or +24 h, creatinine hold), magnesium_tiers (3 tiers, IV in g with a duration, oral 400 mg twice daily for 2 days, recheck at +48 h on the oral tier only, eGFR hold), anemia_iron (iron panel, ferritin, oral ferrous sulfate by tier, eGFR hold). Several NDC and LOINC codes are invented because the benchmark has none (IV KCl, oral magnesium, iron product, iron/ferritin LOINC); judges check them against the text only. Tier thresholds were moved by the writers to make every tier have patients.
- sha256 (first 16) modules: p_potassium_iv d271aee61ca61377, p_magnesium_tiers ca8a6562d1eecad4, p_anemia_iron db4f4e9426504ab0. Wards: potassium_iv 41e64cb8371dbb75, magnesium_tiers 0de24226ecb75189, anemia_iron 6d274f4a93fd094d.
- Rule scripts under the judges, run before the freeze: 18/18, 17/17, 12/12, no false orders.
- **Events:** potassium_iv 32 (18 need orders, 2 held, 12 none), magnesium_tiers 32 (17, 3, 12), anemia_iron 25 (12, 1, 12). Runs per event 8/4/3: 188, 184, 136 = 508 per arm. Pooled: 376 runs on events needing orders, 24 hold runs, 108 none runs.
- **Arms:** `watch` (the product, gates.WATCH) is primary; `checked` (WATCH_CHECKED) is reported as secondary. Nemotron 3 Super 120B on Nebius, temperature 1.0, top_p 0.95, max_tokens 8192.
- **Code frozen:** tool_agent.py 35e6a7dc9121a444, gates.py 7d7cc3a841bda33e, tasks.py 25eeaf11a310dd03, bank_run.py 841db0c9df94ed93.
- **Scored set:** orders the gates accepted and not superseded.
- **No edit to src/, protocol modules, wards or judges between this freeze and the report.** A judge bug found after the run is reported as found, with a clearly labelled second table.

## Criteria, for the `watch` arm, fixed before any output

- **SUPPORTED:** pooled end to end (complete and accurate among the 376 need-order runs) at least 90%; every protocol at least 80%; orders on at most 2 of 24 hold runs; at most 2 false orders in 108 none runs.
- **FAILS:** pooled end to end below 85%, or orders on more than 5 of 24 hold runs.
- Anything else is CAUTION.
- `checked` is reported without a bar; it is credited only if it beats watch by 3 points pooled with hold and false orders no worse by more than 3 combined.
- The rule script is the reference, not a pass bar.

## What will not be concluded

Nothing about real hospitals, clinicians, other models, or protocols other than these three. Judges and oracles were written by model agents and not independently audited; an unfair judge would show up as a failure and would be reported, not hidden.
