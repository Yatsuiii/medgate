# Which Nemotron for which job: model comparison on Token Factory

**Status: FROZEN 2026-10-24 before any model run in this comparison.** The sha256 of this file goes into NOTES.md first.

## Question

Every result so far is from one model, `nvidia/nemotron-3-super-120b-a12b`. Token Factory lists four other NVIDIA text models that accept tool calling (smoke-tested 2026-10-24): `NVIDIA-Nemotron-3-Nano-30B-A3B`, `Nemotron-3_5-Lightning`, `Nemotron-3-Ultra-550b-a55b`, and the Super VL variant (not tested; it is a vision model). Does a smaller or larger model do this job as well, at what token cost, and where does each model fail? A cheaper model that is safe would justify a cascade design; a larger one that is no better would show Super is the right choice.

## Fixed design

- **Protocols:** sodium_high (BUN), phosphate_oral, lab_pair_urgent (WBC): the second confirmation's set (analysis/protocols, wards unchanged: sodium_high daa40357bb515dcd, phosphate_oral b22a75cd603bfd5a, lab_pair_urgent 979cca5bc2629d3d; judges unchanged and the clock-time judge bug does not touch them). 600 runs per model (440 need-order runs: 88, 56, 296; 52 hold runs; 108 none runs).
- **Models:** Nano 30B-A3B, Lightning, Ultra 550B, each on the frozen code (tool_agent.py 13dc24caed7f3c3d, gates.py 7d7cc3a841bda33e, tasks.py 02fc500bc3547875, bank_run.py 841db0c9df94ed93) via analysis/model_compare.py, which only adds a token count. Same sampling for all (temperature 1.0, top_p 0.95, max_tokens 8192), which may not be each model's recommended setting; that is a limit. `watch` config.
- **Baseline for Super:** the dev3 run of 2026-10-24 on the same code, same protocols (sodium_high 77/88, phosphate_oral 55/56, lab_pair_urgent 284/296, pooled 416/440 = 94.5%; zero hold or false orders). That run was development for the re-review change, so it is a same-code baseline, not a pre-registered one. Token counts for Super are measured by re-running a 60-run sample with model_compare.py.
- **Metrics per model:** pooled end to end (complete and accurate among need-order runs), per protocol, misses (silent) and incomplete sets, orders on hold runs (52), false orders (108), model calls per run, prompt and completion tokens per run. Cost in dollars only if prices are supplied by the user from the Token Factory console; otherwise tokens.
- **Spend gate:** Nano and Lightning run in full. Ultra runs in full only if (tokens per run measured on its first 40 runs) x 600 x the Ultra price the user supplies is at most $20; otherwise Ultra runs on the first 3 repeats of need-order events only and the report says so.

## Criteria, fixed before any output

- A model is **ADEQUATE** if pooled end to end is at least 90%, every protocol at least 80%, orders on at most 4 of 52 hold runs, and at most 2 false orders in 108.
- A model is **SAFE TO SCREEN WITH** (the condition for building a cascade where it triages and a larger model drafts) if pooled end to end is at least 85% AND silent misses are at most 3% of need-order runs AND hold plus false orders are at most 6 combined.
- **Larger is better** only if Ultra beats Super's baseline by at least 3 points pooled; otherwise "no evidence the larger model helps".
- A cascade (new code) is built only if some model smaller than Super is SAFE TO SCREEN WITH. If none is, that is the result: Super is the right size for this job on these protocols.

## What will not be concluded

Nothing about other protocols, other prompts tuned per model, or real hospitals. Single sample setting for all models. Token cost is not a price. The models were not tuned per model; a model that fails here may do better with its own settings.
