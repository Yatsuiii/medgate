# Devpost draft (not final)

Every `[BRACKETED]` item is a placeholder that only a real model run can fill. Do not submit with any of them left in. Facts without brackets are measured in this repo or cited in docs/PAIN.md.

## Name

medgate

## Tagline

The lab result came back wrong. Nobody saw it for hours. medgate has the order ready when someone looks. Nemotron on Nebius.

## Track

Best Apps and Agents. (Not Coding and Agentic Engineering: the official rules define that track as agents that write, run and test code, and medgate is not one. Stage One is a pass/fail check that a project genuinely attempts its track's goal.)

## Inspiration

A hospital runs on people remembering things. Someone has to notice that a patient's potassium is low, recall what the unit's protocol says to do, work out the dose, write the order, and remember to recheck in the morning, between twenty other patients. When one of those steps slips, the patient waits, and nobody did anything careless. The system just asked a tired person to be the safety net.

The research agrees that it slips. Between 6.8% and 62% of outpatient lab tests were never followed up in one review of 19 studies (Callen 2012), and even a ward with a good nurse protocol took 112 minutes from result to dose (Gopalsami 2023).

We wanted the order to be waiting when the person looks, so their time goes to judging it instead of building it.

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

Every test was written down, with its pass line, before the model ran. We report the ones that failed.

- **Benchmark pilot (30 tasks, Stanford's own grader):** the same Nemotron scored 13/30 on the benchmark's reference loop and 27/30 with our tool-calling agent. 30 tasks is a pilot.
- **Protocols the agent had never seen, written only as plain text:** 407 of 440 orders right (92.5%), with no order on any hold event and no false order. That was the second clean attempt. The first scored 88.3% and we called it caution.
- **A set that failed:** the third set scored 53% as registered, because our own grader rejected a correct default. We fixed the grader, rescored from saved transcripts (93%), and labelled it after the fact.
- **A second Nemotron as checker:** Super or Ultra, seeing only the protocol, the record values and the drafted orders, caught 31 of 33 (Super) and 30 of 33 (Ultra) wrong order sets and flagged none of 80 correct ones, for about $0.08 of tokens. This measures detection only. Feeding its findings back to the drafter is untested.
- **Against a simple rule script:** the script wins on accuracy. What the agent adds is that a unit writes a protocol as text instead of code.

Details and every failure: docs/ in the repository.

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

- Working demo (a read-only recorded scan of the live model; running it yourself is in the README): https://yatsuiii.github.io/medgate/demo/
- Repository: https://github.com/Yatsuiii/medgate
- Demo video (under 3 minutes): [YOUTUBE URL]

## Notes for the form

- New project, started 2026-10-12 during the hackathon window, so no "what changed" note should be needed. Confirm against the rules page before submitting.
- No session or transcript links anywhere in the form, repo or video description.
