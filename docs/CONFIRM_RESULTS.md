# Clean confirmation on three fresh protocols: results

Pre-registered in docs/CONFIRM_PREREG.md (sha256 7db3bfb196601935f6beb26db76306c445332cfb7ab832cf64e1b9290e02c6bb, logged in NOTES.md before the runs). Code, protocol modules, wards and judges unchanged between freeze and report. Nemotron 3 Super 120B on Nebius, 508 runs per arm. Evidence label: VERIFIED for the numbers; the judges are model-written and unaudited.

## Verdict: CAUTION (not SUPPORTED, not FAILED)

Bar for SUPPORTED was pooled 90% or more. The product arm got 88.3%, so the clean claim is not met; it is above the 85% fail line. Nothing was moved or rescored.

| arm | protocol | end to end | misses | incomplete | hold orders | false orders |
|---|---|---|---|---|---|---|
| watch | potassium_iv | 124/144 (86.1%) | 1 | 2 | 0/8 | 0/36 |
| watch | magnesium_tiers | 115/136 (84.6%) | 2 | 1 | 0/12 | 0/36 |
| watch | anemia_iron | 93/96 (96.9%) | 0 | 1 | 0/4 | 0/36 |
| watch | pooled | 332/376 (88.3%) | 3 | 4 | 0/24 | 0/108 |
| checked | pooled | 337/376 (89.6%) | 1 | 6 | 0/24 | 0/108 |

Per criterion for watch: pooled 88.3% (needs 90, fails), every protocol at least 80% (met), hold orders 0 of 24 (met), false orders 0 of 108 (met). Checked beats watch by 1.3 points pooled, under the 3 points needed, so the extra checks are not credited. Rule scripts: 100% on all three. Model calls per run about 4.6 to 5.7.

## What the failures were (read from transcripts, not rescored)

- All 40 failures are on events that need orders: 7 misses or incomplete sets, the rest complete sets with a wrong or missing field. Safety side was clean: no order on any hold event, none where the protocol says order nothing.
- Magnesium oral order drafted without `priority: routine`, which the text asks for (agent omission).
- Magnesium IV order written with a `rateQuantity` of 1 h next to `boundsDuration` of 4 h: contradictory, and the judge reads the rate first. Whether the judge is too strict here is arguable; I did not change it.
- Potassium IV order first sent with `dosageInstruction` as a JSON string, rejected by the payload gate and retried; the final accepted payloads of failing runs differ in some field. I did not classify all 17.
- A full failure-class breakdown of the 40 was not done.

## What this says

The agent drafts correctly 88% of the time on protocols it had never seen, with no unsafe order, and a person approving each order is still necessary. The claim "a unit adds a protocol as text and gets correct drafts with no code" holds with a 1 to 2 in 10 error rate on order contents, not at the 90% bar. The earlier 254/256 was on protocols a few bugs had already been fixed for; this is the more honest number. Still synthetic data, one model, model-written protocols, invented NDC and LOINC codes, no clinician.
