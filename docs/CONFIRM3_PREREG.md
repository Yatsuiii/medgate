# Third clean confirmation on three fresh protocols

**Status: FROZEN 2026-10-24 before any model run on these protocols.** The sha256 of this file goes into NOTES.md first. A later change is a dated deviation note.

## Why

docs/CONFIRM2_RESULTS.md: 407/440 (92.5%), SUPPORTED, but 21 of the 33 failures were incomplete order sets: the agent wrote the drug order after the finish-time review and finished without the paired recheck or second order. One generic change followed: the finish-time review now runs once more when any order is written after the first review (RE_REVIEW in tool_agent.py, capped at one extra). A dev re-run of the six protocols seen so far went from 73/88, 55/56, 279/296, 138/144, 129/136, 94/96 to 77/88, 55/56, 284/296, 138/144, 132/136, 90/96 (776/816, 95.1%), with no hold or false orders. That run is development: the change was chosen after reading those failures. This test asks whether it holds on protocols no run or change has touched.

## Fixed design

- **Protocols** (analysis/protocols/), each written blind by a separate agent with its own oracle, judge and rule script: two_drugs_one_lab (low bicarbonate CO2: an oral drug twice daily for 3 days, an IV drug over 2 hours, a repeat CO2 at +12 h, calcium hold), clock_time_recheck (low bicarbonate CO2: tiered single oral dose, urgent, repeat CO2 at an absolute 06:00 UTC next day, eGFR hold), drug_plus_stat_lab (low chloride CL: oral drug twice daily for 5 days by tier, a stat panel now, a repeat chloride at +24 h on the severe tier only, eGFR hold). **Not independent in one respect:** the first two share the CO2 trigger lab and patients and the bicarbonate topic. Invented or unchecked codes: all three oral/IV NDCs and the LOINC codes were chosen by the writers from memory; the benchmark has none.
- sha256 (first 16): p_two_drugs_one_lab 4f4829792b1f122f, p_clock_time_recheck f6182ae3b5c92f74, p_drug_plus_stat_lab b797dbc713723cd7. Wards: two_drugs_one_lab 92fa9d0027fdde63, clock_time_recheck d484bf810d60d0e8, drug_plus_stat_lab f45192e994b89fcc.
- Rule scripts under the judges, run before the freeze: 7/7, 13/13, 10/10, no false orders.
- **Events:** two_drugs_one_lab 21 (7 need orders, 2 held, 12 none), clock_time_recheck 27 (13, 2, 12), drug_plus_stat_lab 26 (10, 4, 12). Runs per event 8/4/3: 100, 148, 132 = 380. Pooled: 240 runs on events needing orders (56, 104, 80), 32 hold runs, 108 none runs. clock_time_recheck is 43% of the order runs; per-protocol rates are reported beside the pooled one.
- **Arm:** `watch` only (gates.WATCH). Nemotron 3 Super 120B on Nebius, temperature 1.0, top_p 0.95, max_tokens 8192. Run three protocols at a time to stay under the rate limit.
- **Code frozen:** tool_agent.py 13dc24caed7f3c3d, gates.py 7d7cc3a841bda33e, tasks.py 02fc500bc3547875, bank_run.py 841db0c9df94ed93.
- **Scored set:** orders the gates accepted and not superseded.
- **No edit to src/, protocol modules, wards or judges between this freeze and the report.** A judge bug found afterwards is reported as found, with a clearly labelled second table.

## Criteria, fixed before any output

- **SUPPORTED:** pooled end to end (complete and accurate among the 240 need-order runs) at least 90%; every protocol at least 80%; orders on at most 3 of 32 hold runs; at most 2 false orders in 108 none runs.
- **FAILS:** pooled below 85%, or orders on more than 4 of 32 hold runs.
- Anything else is CAUTION.
- Incomplete sets are reported on their own line, since the change targets them.
- The rule script is the reference, not a pass bar.

## What will not be concluded

Nothing about real hospitals, clinicians, other models, or other protocols. Judges and oracles are model-written and unaudited. This is the third attempt after two earlier ones (88.3% CAUTION, then 92.5% SUPPORTED); each followed a change made after reading failures, so the series is a forking path and a pass says only that this agent, with these tools, handled these three texts.
