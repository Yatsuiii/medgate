# Devpost draft (not final)

Every `[BRACKETED]` item is a placeholder that only a real model run can fill. Do not submit with any of them left in. Facts without brackets are measured in this repo or cited in docs/PAIN.md.

## Name

medgate

## Tagline

A results watch for the hospital record: new lab results in, ready-to-sign protocol orders out, nothing written until a clinician approves. Nemotron on Nebius.

## Track

Best Apps and Agents. (Not Coding and Agentic Engineering: the official rules define that track as agents that write, run and test code, and medgate is not one. Stage One is a pass/fail check that a project genuinely attempts its track's goal.)

## Inspiration

Abnormal lab results get acted on late or not at all. A systematic review of 19 outpatient studies found 6.8% to 62% of laboratory tests were never followed up, with hospital visits for high potassium after a missed result among the harms (Callen 2012). Doctors in one study received about 77 inbox notifications a day, a fifth of them test results (Murphy 2016). And even where a nurse protocol exists, one ward still took 112 minutes from a low result to the dose, down from 344 (Gopalsami 2023). Protocols help a great deal. They still wait for a person to notice the result and build the order.

Sources and what was checked on the primary page are in docs/PAIN.md.

## What it does

medgate watches a ward and does the noticing.

- For each patient and each unit protocol, it takes the newest result the protocol covers that arrived in the last 24 hours. Code never decides what is abnormal.
- An NVIDIA Nemotron agent reads the protocol's own text and either drafts the orders it calls for (dose computed, the recheck lab paired) or orders nothing. It checks exclusions in the record. In the demo, magnesium is held for pharmacist review when the newest eGFR is below 45.
- Every order cites the lab result it is based on, in FHIR's own `reasonReference`. A gate rejects a citation to a record the agent never retrieved.
- The worklist shows the ready orders beside the cited lab. Nothing reaches the FHIR server until a clinician approves. An approved order is written as conformant FHIR, then read back and compared field by field.

The same screen also answers a question about one patient.

## How we built it

- Python, uv, httpx; ruff and pyright strict. No web framework and no new dependency for the screen.
- Model: `nvidia/nemotron-3-super-120b-a12b` on Nebius Token Factory through its OpenAI-compatible API, native tool calling.
- The agent follows MedAgentBench v2's published design (structured tool per FHIR function, calculator, planning prompt), written from the paper, with no v2 code used. Search results come back compact and newest first, because GPT-4.1's published runs showed 33 failures from reading only part of a result list.
- The benchmark's FHIR server, run locally. The benchmark's own grader scores the agent. MedAgentBench tasks 5 and 9 are this exact workflow, so the watch is graded against the benchmark's cases.
- 210 tests that need no server, plus live tests against the FHIR server and the real grader, tests that run the model client over real HTTP against a fake endpoint with rate limits and malformed replies, and mutation checks showing a test fails when a check is broken.

## What we measured

Fixed before any model output (docs/PILOT_PREREG.md, sha256 in NOTES.md): 30 tasks, 3 per category, Nemotron on the benchmark's reference loop (A) and our tool agent (T), one run per task, graded by the benchmark's own grader.

- A: 13/30. T: 27/30. Only T correct on 15 tasks, only A correct on 1 (McNemar exact p = 0.0005). With 30 tasks a 95% interval is about plus or minus 17 points, so this is a pilot. Same model, only the harness changed.
- T's three failures by class: retrieval 2 (a patient name put whole into the given-name field with no retry; a 24-hour average built from 2 of 4 results because the FHIR server's date filter dropped in-window records), payload 1 (a patient reference without its `Patient/` prefix, which the gates as built do not catch). Classified by three independent readers per failure, then a vote.
- The decision rule applied as written: 27 of 30 is the "27 or more" line, so there is little room for gates, and the claim that gates raise task success is dropped. We make no claim of parity with GPT-4.1's published 91.0%: the harness differs and 30 tasks is a pilot.
- The watch on the demo ward, 36 runs on Nemotron under criteria fixed beforehand: 23 of 27 graded runs correct (bar 22), nothing ordered on the 9 runs where the protocol says not to (including a kidney-function hold), and every drafted order cites its lab result. That met the criteria narrowly. The failures were mostly silent misses: the agent finished without ordering what the protocol calls for, and the structural gates do not see that.
- The fix, tested on 44 held-out events from patients never on the demo ward (criteria fixed before the run, both arms side by side): a one-time review, in which the agent is shown its own orders and asked to check them against the protocol text before it finishes. Silent misses on the 12 events that need orders went from 33 of 120 runs to 0, with no false orders in 134 runs each and no order on the event that should be held. Complete and accurate order sets rose from 62% to 90%. The cost is about 1.3 more model calls per run. A side effect we found: in 6% of runs the review leads the agent to create a corrected order next to the original, so the screen marks the earlier draft superseded.

- Against a hand-coded rule script on the same held-out events, the rule wins on accuracy (12 of 12 against the agent's 90% end to end, no model, 26 lines). We said so before running it (docs/RULESET_PREREG.md). What the agent adds is that a unit writes a protocol as text instead of code, so we tested that on protocols nobody tuned for.
- A calcium protocol (a relative recheck time, an albumin hold) scored 64 of 80 (80%) against our 90% bar, so that claim failed the first time. Most of the gap was the rate written as `1 g/h` instead of hours.
- A bank of 7 more protocols, each with an independent oracle, a judge and a rule script, designed and cross-checked by separate model agents. Four were used to find problems, three were frozen as a test. The frozen test failed as run (43% against an 85% floor) because the order tool for drugs had no field for priority. After adding standard FHIR fields for frequency, duration and priority to the watch's tool, the three protocols scored 254 of 256 for the watch (the labelled follow-up, made after seeing the test, so not a clean pass). A clean confirmation on three fresh protocols (frozen code, criteria fixed first) scored 332 of 376 (88.3%) for the watch against a 90% bar, with no order on any hold event and no false order, so the verdict is caution (docs/CONFIRM_RESULTS.md). The failures were orders accepted with no route or no infusion duration, so the watch's drug order tool now requires a route and a dose. On three more protocols nobody had run (frozen code, criteria fixed first) it scored 407 of 440 (92.5%), met every criterion, with no order on any hold event and no false order (docs/CONFIRM2_RESULTS.md). It is the second clean attempt, after a first at 88.3%. A third set, after a second finish-time review for orders written late, failed as pre-registered (128 of 240) because one protocol's judge rejected an omitted timing that the tool defines as a single dose; rescored from the saved transcripts with that one judge change it is 224 of 240 (93.3%), labelled post hoc (docs/CONFIRM3_RESULTS.md). A separate-model verifier (a second Nemotron that sees only the protocol, the record values and the drafted orders) caught 31 of 33 wrong or incomplete order sets and wrongly flagged none of 80 correct ones in a replay on saved runs, for about \$0.08 of tokens; it measures detection, and feeding its findings back to the drafter is untested (docs/VERIFIER_RESULTS.md). Prompt changes (a field-by-field check, a time gate) helped on one dev protocol and not on the test; the tool fixes were what mattered.

Already measured without a model, so stated as plumbing and not accuracy: scripted correct agent runs for the 9 of 12 demo events that belong to benchmark patients of the matching task are graded correct by the benchmark's grader, every order cites its result, and an approved order reads back whole.

## Challenges

- The benchmark's reference loop never sends writes to the server, so checking a write by reading it back is impossible there. The review screen does write, and reads back.
- The FHIR server accepts a medication route given as plain text, which is the shape the grader requires, and silently stores the order without it. Commit converts the route and the read-back caught the difference.
- GPT-4.1's published runs fail mostly on answer format (96 of 125 failures), not clinical reasoning. The agent nudges once when a final answer is a sentence or an object, and never blocks.

## Accomplishments

- A tested end-to-end path from a new lab result to a ready, cited order a person approves, graded by an external benchmark.
- A pilot protocol with the decision rule written before any model output.

## What we learned

- The harness mattered more than any check we added: the same model went from 13 to 27 of 30 when only the harness changed. That is why the baseline has to be the strongest realistic one, and why our own pre-registered rule dropped the claim that gates raise task success.
- Gates see structure, not meaning. A wrong patient or a forged citation is blocked every time. A dose ten times too low, a wrong route and a missing paired order pass. The person reviewing the order is the only barrier for those.
- The failure that matters most for a results watch is the silent miss: the agent finishes without ordering. It is not on the worklist, and it reads like "nothing to do". A one-time self-review before finishing removed it on held-out events, which a structural gate could not.
- The form the agent writes orders in decides more than the prompt: both big failures were an order tool that could not say 'twice daily for 2 days' or 'priority routine'. Fixing the tool beat tuning the prompt.
- For fixed, well-known protocols a coded rule is more accurate than a model. The case for the model is a unit adding a protocol as text; across the 10 protocols we tried it ranged from 77% (glucose) and 80% (calcium) to about 98% (the three final-test protocols after the tool fix), so a person still has to check each order.
- Pre-registering before the first model call, and writing down what each result would and would not show, made it easy to report a narrow pass and a weak spot without spin.

## What's next

- Check that the review's gain holds on other models and longer protocols, and measure how often a reviewer notices a wrong dose.
- Ask clinicians whether a ready-written order beats an order set with an alert. Nothing here tests that yet. No clinical use is claimed.

## Feedback on Nebius Token Factory, AI Cloud and NVIDIA tools

Written from what happened in this project (the form requires it). Used: Token Factory with Nemotron 3 Super. Not used: AI Cloud, Serverless Endpoints or Jobs.

- **What worked:** the OpenAI-compatible endpoint and native tool calling worked with `nvidia/nemotron-3-super-120b-a12b` with no client changes beyond the base URL and key. Thousands of five-call agent runs cost a small share of the credit, which made it practical to pre-register many tests.
- **Rate limits:** with 36 requests in flight (six protocols at six workers each) the endpoint returned HTTP 429 and a run stopped after five retries. Eight to 24 in flight was fine. A documented concurrency limit and a `Retry-After` value on 429 would let a client back off instead of failing. I do not know whether either exists; I did not find one while building.
- **Nemotron behaviour that mattered:** in some runs the model sent a nested array argument (`dosageInstruction`) as a JSON string instead of an array. A schema check on our side caught it and the model corrected it on the next turn. Stricter argument typing for nested arrays in tool calls would remove a class of retries.
- **Model behaviour we liked:** given a protocol as plain text, it ordered nothing on hold and no-order events in all but a handful of the several thousand runs we made, and it used the retrieved record (an exclusion lab) instead of the number in the prompt.
- **Model choice:** we also tried Nano, Lightning and Ultra on the same job (partial runs, stopped for budget; docs/MODELS_RESULTS.md). Nano missed orders and spent about 52,000 reasoning tokens per run, so it was not cheaper than Super per run; Lightning looped (about 235,000 prompt tokens per run) and failed; Ultra matched Super on one protocol at about twice the calls. Super was the right size for this job.
- **Spend visibility:** the console's usage page breaks cost down by model, which is good, but it carries a "last updated" delay and the balance lagged, so I could not watch spend while a batch ran and the balance fell from \$10.64 to \$4.36 during one experiment. A live balance, or the cost of each request in the API response next to the token counts, would let a client stop itself at a budget.

## Honest limits

- Synthetic benchmark patients. No clinical claims and no clinician has used it.
- The claimed edge over existing protocol order sets (the order arrives already written, so acting takes one tap) is a hypothesis. Nothing has tested it.
- The demo protocols are short and written from the benchmark's task wording. The renal exclusion value (eGFR below 45) is invented for the demo.
- One model, one sample per task, 30 pilot tasks and 36 watch runs. Intervals are wide (about plus or minus 15 to 17 points).
- 12 of 120 runs with a complete order set still have a wrong dose, duration or time, so a person has to check each order.
- A coded rule beats the model on accuracy for these protocols. The protocols were designed by model agents, not clinicians, and several protocols went through a judge or tool bug found after a run. The final test's pass is a post-hoc follow-up, not a clean pre-registered pass.

## Built with

python, uv, httpx, fhir, nebius, nemotron, medagentbench

## Links

- Working demo (a read-only recorded scan of the live model; running it yourself is in the README): [DEMO URL, after enabling GitHub Pages: https://ACCOUNT.github.io/REPO/demo/]
- Repository: [PUBLIC REPO URL]
- Demo video (under 3 minutes): [YOUTUBE URL]

## Notes for the form

- New project, started 2026-10-12 during the hackathon window, so no "what changed" note should be needed. Confirm against the rules page before submitting.
- No session or transcript links anywhere in the form, repo or video description.
