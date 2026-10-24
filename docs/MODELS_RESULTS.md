# Which Nemotron for which job: partial results

Pre-registered in docs/MODELS_PREREG.md (sha256 in NOTES.md before any run). The comparison was **cut short for budget**: the Token Factory balance fell from \$10.64 to \$4.36 during it, so all runs were stopped with the samples below. Nothing here is a full test. Same frozen agent code and sampling for every model (temperature 1.0, top_p 0.95); models were not tuned per model. Tokens come from the endpoint's own usage counts. Prices are known only for Nano and Super (Billing > Prices); Lightning and Ultra are not on that page, so no dollar figure is given for them.

## What was run

| model | runs saved | protocol(s) | end to end | misses | false orders |
|---|---|---|---|---|---|
| Ultra 550B | 40 of 600 | phosphate_oral, need-order runs only | 39/40 (97.5%) | 0 | not sampled |
| Nano 30B-A3B | 11 of 600 | sodium_high 2, phosphate_oral 9 | 4/8 complete sets accurate | 3 of 9 on phosphate | not sampled |
| Lightning | 178 of 600 | sodium_high 132, phosphate_oral 46 | 19/90 complete sets accurate | 24 of 130 | 14 of 48 |
| Super 120B (same code, dev run) | 600 | all three | 416/440 (94.5%); phosphate 55/56 (98.2%) | 4 of 440 | 0 of 160 |

## Tokens per run

| model | prompt | completion | model calls |
|---|---|---|---|
| Ultra | 80,572 | 4,724 | 9.1 |
| Nano | 78,802 | 52,280 | 10.2 |
| Lightning | 235,540 | 2,648 | 10.4 |
| Super (for reference) | about 30,000 | about 1,400 | about 4 to 6 |

Super's figures are from the console totals over the whole series (about 258M tokens over about 8,000 runs), not from a counted sample.

## What it shows, and does not

- **No smaller model was safe to screen with.** Nano missed 3 of 9 need-order runs on phosphate and was right on half of its complete sets; Lightning failed the ADEQUATE bar by a wide margin (19 of 90 sets accurate, 14 false orders in 48 hold or no-order runs, partly a ward made of hold events). By the pre-registered rule the cascade was not built. Samples are small (Nano 11 runs), so Nano's number is weak evidence; Lightning's is not.
- **Smaller was not cheaper per run.** Nano's list prices are lower, but it spent about 52,000 completion tokens per run on reasoning. At its prices (\$0.06 per million input, \$0.24 per million output) that is about \$0.017 per run, against roughly \$0.005 for Super from the console totals. Lightning used about eight times Super's prompt tokens per run, through longer agent loops.
- **Ultra was as accurate as Super on one protocol, at about twice the calls and tokens.** 39/40 against Super's 55/56 on phosphate_oral; no misses. That is not "larger is better" (it needed a 3-point gain) and the sample is one protocol. Its price is unknown, so cost per run is unknown.
- **Super is the right size here, on this evidence.** It is the only model with a full pre-registered record, and nothing in the partial runs beat it on accuracy or cost. The honest limit: three of the four models are barely sampled.
- **Not covered:** per-model sampling settings, other prompts, the Super VL model (a vision model), Nebius AI Cloud.
- **Measured vs unmeasured:** in-flight requests at the stop (Nano, Ultra) were lost and not counted. The balance fell \$5.94 over a window that included these runs and the Lightning runs; how it splits across models is UNKNOWN until the usage page refreshes.
