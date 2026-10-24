# Second clean confirmation on three fresh protocols

**Status: FROZEN 2026-10-23 before any model run on these protocols.** The sha256 of this file goes into NOTES.md first. A later change is a dated deviation note.

## Why

docs/CONFIRM_RESULTS.md: the first clean confirmation scored 332/376 (88.3%) for the watch against a 90% bar, so CAUTION. The failures (read from transcripts) were mostly orders accepted with no route, no infusion duration, or no priority. One generic fix followed: the watch's drug order tool now requires a route and a dose (benchmark tool unchanged) and describes the rate field. A dev re-run of the same three protocols went from 332/376 to 361/376 (96.0%); that run is development, because the fix was chosen after seeing those failures. This test asks whether the fix holds on protocols neither the fix nor any run has touched.

## Fixed design

- **Protocols** (analysis/protocols/), each written blind by a separate agent with its own oracle, judge and rule script: sodium_high (file name; the lab is BUN: IV saline by tier with a duration in hours, urgent priority, paired repeat BUN at +12 h, creatinine hold), phosphate_oral (oral phosphate by tier, 3 times daily for 3 days, routine, eGFR hold, no recheck), lab_pair_urgent (WBC; labs only: stat CBC with differential now, routine repeat WBC at +12 h, urgent blood culture at the severe tier only, platelet hold). Invented or unchecked codes: saline NDC 0338-0049-04, phosphate NDC 0095-0183-01, LOINC codes recalled from memory. Tier cut points were set by the writers so each tier has patients; BUN-for-saline is clinically a stretch.
- sha256 (first 16): p_sodium_high 95f6f87eb93367fe, p_phosphate_oral 7292c7143f2e02dd, p_lab_pair_urgent 3d0dcd1aa3fbcc64. Wards: sodium_high daa40357bb515dcd, phosphate_oral b22a75cd603bfd5a, lab_pair_urgent 979cca5bc2629d3d.
- Rule scripts under the judges, run before the freeze: 11/11, 7/7, 37/37, no false orders.
- **Events:** sodium_high 25 (11 need orders, 2 held, 12 none), phosphate_oral 21 (7, 2, 12), lab_pair_urgent 58 (37, 9, 12). Runs per event 8/4/3: 132, 100, 368 = 600. Pooled: 440 runs on events needing orders (88, 56, 296), 52 hold runs, 108 none runs. The pooled rate is dominated by lab_pair_urgent (67%); the per-protocol rates are reported beside it.
- **Arm:** `watch` only (gates.WATCH). The `checked` arm added nothing in the earlier tests and is dropped. Nemotron 3 Super 120B on Nebius, temperature 1.0, top_p 0.95, max_tokens 8192.
- **Code frozen:** tool_agent.py 35e6a7dc9121a444, gates.py 7d7cc3a841bda33e, tasks.py 02fc500bc3547875, bank_run.py 841db0c9df94ed93.
- **Scored set:** orders the gates accepted and not superseded.
- **No edit to src/, protocol modules, wards or judges between this freeze and the report.** A judge bug found afterwards is reported as found, with a clearly labelled second table.

## Criteria, fixed before any output

- **SUPPORTED:** pooled end to end (complete and accurate among the 440 need-order runs) at least 90%; every protocol at least 80%; orders on at most 4 of 52 hold runs; at most 2 false orders in 108 none runs.
- **FAILS:** pooled below 85%, or orders on more than 6 of 52 hold runs.
- Anything else is CAUTION.
- The rule script is the reference, not a pass bar.

## What will not be concluded

Nothing about real hospitals, clinicians, other models, or other protocols. Judges and oracles are model-written and unaudited; an unfair judge would show up as a failure and be reported, not hidden. A pass here says this agent, with this tool, handled these three texts.
