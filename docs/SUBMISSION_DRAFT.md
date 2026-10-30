# Devpost draft (not final)

Every `[BRACKETED]` item is a placeholder that only a real model run can fill. Do not submit with any of them left in. Facts without brackets are measured in this repo or cited in docs/PAIN.md.

## Name

medgate

## Tagline

The lab result came back wrong. Nobody saw it for hours. medgate has the order ready when someone looks. Nemotron on Nebius.

## Track

Best Apps and Agents. (Not Coding and Agentic Engineering: the official rules define that track as agents that write, run and test code, and medgate is not one. Stage One is a pass/fail check that a project genuinely attempts its track's goal.)

## Inspiration

A hospital runs on people remembering things. Picture a ward late in a long shift. A potassium result comes back low. Someone has to notice it among everything else in their inbox, recall what the unit's protocol says, work out the dose, write the order, and remember to recheck the level in the morning. Each of those steps is a place where the patient can wait, and nobody in that chain was careless. The system asked a tired person to be the safety net.

The research agrees that the steps slip. A systematic review of 19 studies found that between 6.8% and 62% of laboratory tests in outpatients were never followed up, and it lists hospital visits for hyperkalaemia after missed abnormal potassium results among the reported harms (Callen et al., 2012). Protocols help a great deal. On a haematology ward, a nurse-driven electrolyte protocol cut the average time from lab result to medication from 344 minutes to 112 (Gopalsami and Wheatley, 2023). But a protocol is still a document. It waits for a person to notice the result and then to build the order by hand.

So we asked a narrow question: what if the order were already written, with the lab result beside it, by the time the person looks? Their time would go to judging the order instead of building it.

The hard part is that every unit writes its protocols differently, in plain text, and they change. Code that encodes a protocol is accurate (we measured it: a coded rule script beats our agent on accuracy), but someone has to write and maintain that code for every protocol. A model that reads the protocol as written moves that work. That is the idea medgate tests, with an NVIDIA Nemotron model on Nebius Token Factory reading the protocol, and with a person approving every order.

Sources, and which numbers we checked on the primary page, are in docs/PAIN.md.

## What it does

medgate is a results watch with a review screen in front of the chart. You give it a ward, meaning a list of patients, and the unit's protocols as plain text. The demo ward is seven synthetic patients and two protocols, potassium replacement and magnesium replacement.

**It notices.** When you press Check new results, medgate takes, for each patient and each protocol, the newest result the protocol covers that arrived in the last 24 hours. That selection is all the code decides. Code never decides what is abnormal.

**It reads the protocol and drafts.** An NVIDIA Nemotron agent on Nebius Token Factory receives the protocol's own text and the result. It looks up what it needs in the patient's record, then either drafts the orders the protocol calls for or orders nothing. For a potassium of 3.1 mmol/L, the demo protocol calls for oral potassium chloride, 40 mEq, plus a paired recheck of serum potassium, stat, due the next morning at 08:00. The agent computes the dose and drafts both orders. The magnesium protocol has an exclusion: if the newest eGFR is below 45, order nothing and hold for pharmacist review. The agent has to look that lab up in the record rather than trust the number in front of it. (The 45 is an invented demo value.)

**It cites its evidence.** Every order carries the lab result it is based on, in FHIR's own reasonReference field, and the card shows it, for example "Based on Observation/330934: K 3.1 mmol/L". A gate checks that every cited record was actually retrieved during the run, so the agent cannot cite something it never looked at.

**It puts the work in front of a person.** A scan of the demo ward takes about 20 to 30 seconds. The worklist then shows four tiles (results checked, need action, orders drafted for review, no order), with the rows that need a person first. Each order card shows the patient, dose, route, priority and due time, the cited lab, the gate result, Approve and write and Reject buttons, and the raw FHIR payload. Rows with no order are not hidden. They show the agent's own note when it left one, and an Agent steps view lists every lookup it made. The page says outright when the agent's reason is not checked.

**It blocks what it can see.** If a drafted order fails a structural check, the card shows the gate's message and the button changes from Approve to Override. In the scan shown in our video, one magnesium order came back with its dosage instruction as a plain string instead of an array. The gate flagged it, the card said so, and we rejected it.

**It writes only when a person says so.** Nothing reaches the FHIR server until a clinician approves. An approved order is converted to conformant FHIR, written, then read back from the server and compared field by field. The screen shows "Read back: every field stored", or lists whatever the server dropped.

**It fails visibly.** If the model endpoint fails on a result, that result stays on the worklist marked as not processed and needing a person. It does not vanish. Before its first finish, the agent reviews its own decision once; when that produces a corrected order next to the original, the screen marks the earlier one superseded so nobody approves both.

The same screen has a second tab that answers a question about one patient. It also runs without a model: a replay mode shows a scripted ward, labelled as a replay, and a read-only hosted snapshot of one real scan is linked below. The server listens on localhost only and has no login, so it is for local demos.

## How we built it

**Stack.** Python with uv and httpx, strict ruff and pyright, no web framework and no new dependency for the screen. The model is `nvidia/nemotron-3-super-120b-a12b` on Nebius Token Factory, called through its OpenAI-compatible API with native tool calling.

**Data and grader.** medgate sits on MedAgentBench, Stanford's benchmark of 300 physician-written tasks over a FHIR record system. We run its FHIR server locally on synthetic patients. Two of its tasks are this exact workflow, task 9 (potassium) and task 5 (magnesium), so a watch run for a benchmark patient is graded by the benchmark's own grader against that patient's case, not by a grader we wrote.

**The agent.** medgate began as a research harness asking whether mechanical checks between an agent and a record system raise task success. The benchmark's reference loop turned out to be a weak baseline: MedAgentBench v2 reached 91.0% with GPT-4.1 using structured tools and a better prompt. So we built a tool-calling agent from the paper's description (no v2 code): one structured tool per FHIR function in the benchmark's own spec, a calculator over an allowlist with no eval, a finish tool that takes a list, and a planning prompt. We added three things because of GPT-4.1's published failures. Search results come back compact and newest first with every match, so the newest value is never on a page the agent did not see (that cost GPT-4.1 33 failures). An empty search tells the agent to try the task's other codes. And the finish tool nudges once when an answer is a sentence or an object, because 96 of GPT-4.1's 125 failures were answer format, not clinical reasoning.

**The gates.** Two pure functions. The payload gate checks every write body for required fields and value types against the benchmark's own tool spec, and failures go back to the agent. The evidence gate checks that a write references only record ids the agent was told or actually retrieved, and that a search for a patient names a patient from the task or from earlier results. Every tool call is also mirrored into the benchmark's own text history, so its grader scores our agent exactly as it scores the reference one.

**The review step.** The failure that matters most for a results watch is the silent miss: the agent finishes without ordering, and the row reads like "nothing to do". So before the first finish, the agent is shown its own orders and asked to check them against the protocol's text. Then the review module turns a run's writes into proposals, each with its payload, what the gates found, and the cited records read back from the server. Only an approved proposal is committed. Commit converts it to conformant FHIR (the medication route becomes a coded concept), writes it, and reads it back.

**Nemotron on Token Factory.** Every agent run in this repo, from the 30-task pilot to the protocol bank and the confirmations, makes runtime calls to Token Factory. The screen runs four agent runs at a time. The evaluation series ran thousands of five-call agent runs, eight at a time, for a small share of the credit, and that is what made it practical to pre-register many tests. We also tried Nano, Lightning and Ultra on the same job, and Super was the right size.

**Testing.** 210 tests that need no server. Live tests against the FHIR server and the real grader. Wire tests that run the model client over real HTTP against a scripted fake endpoint with rate limits and malformed replies (demo/fake_model.py applies the same idea so you can try the screen without a key). And mutation checks showing that a test fails when a check is broken.

**Pre-registration.** Before each experiment's first model call we wrote down the tasks, the pass line, the failure classes and the decision rule. We then reported the result against that rule, including the failures.

## What we measured

Every test was written down, with its pass line, before the model ran. We report the ones that failed.

- **Benchmark pilot (30 tasks, Stanford's own grader):** the same Nemotron scored 13/30 on the benchmark's reference loop and 27/30 with our tool-calling agent. 30 tasks is a pilot.
- **The watch on the demo ward:** 23 of 27 graded runs correct, nothing ordered where the protocol says not to, every order cited. The failures were mostly silent misses. A one-time review before finishing took silent misses from 33 of 120 runs to 0 on 44 held-out events, with no false orders, and complete and accurate order sets rose from 62% to 90%.
- **Protocols the agent had never seen, written only as plain text:** 407 of 440 orders right (92.5%), with no order on any hold event and no false order. That was the second clean attempt. The first scored 88.3% and we called it caution.
- **A set that failed:** the third set scored 53% as registered, because our own grader rejected a correct default. We fixed the grader, rescored from saved transcripts (93%), and labelled it after the fact.
- **A second Nemotron as checker:** Super or Ultra, seeing only the protocol, the record values and the drafted orders, caught 31 of 33 (Super) and 30 of 33 (Ultra) wrong order sets and flagged none of 80 correct ones, for about $0.08 of tokens. This measures detection only. Feeding its findings back to the drafter is untested.
- **What the gates catch (scripted, no model):** 5 of 5 structural mistakes were blocked (wrong patient, forged citation, someone else's lab, missing required field, wrong value type). 4 of 4 mistakes in meaning reached the worklist unflagged (a dose ten times too low, the wrong drug, the wrong route, a recheck on the wrong day). Gates see structure, not meaning, so the person is the only barrier for the second kind.
- **Against a simple rule script:** the script wins on accuracy. What the agent adds is that a unit writes a protocol as text instead of code.

Details and every failure: docs/ in the repository.

## Challenges

- **Our own headline claim did not survive.** We set out to show that gates raise task success. The pilot showed the same model going from 13 to 27 of 30 when only the harness changed, and by our own frozen rule we dropped the claim. The harness mattered more than any check.
- **The benchmark's reference loop never sends writes to the server,** so checking a write by reading it back is impossible there. The review screen does write, and reads back.
- **The FHIR server silently drops a medication route given as plain text,** which is the shape the grader requires. Commit converts the route, and the read-back caught the difference.
- **Silent misses.** The agent sometimes finished without ordering, and the row looked like "nothing to do". 33 of 120 runs did this. A one-time self-review fixed it on held-out events, with a side effect: in 6% of runs it drafts a corrected order next to the original, so the screen marks the earlier one superseded.
- **The order tool, not the prompt.** Both big failures were an order tool that could not say "twice daily for 2 days" or "priority routine". Fixing the tool beat tuning the prompt.
- **A judge bug in our own test.** The third confirmation scored 53% because our grader rejected a correct default. We reported it as a failure, fixed it, and labelled the rescore as after the fact.
- **Rate limits.** With 36 requests in flight, Token Factory returned HTTP 429 and a run stopped after five retries. Eight to 24 in flight was fine.
- **Malformed tool arguments.** In some runs the model sent a nested array argument (`dosageInstruction`) as a JSON string. Our schema check caught it, and the model corrected it on the next turn. The same class of error shows up, flagged, in the scan in our video.
- **The day we recorded,** the benchmark's FHIR database file was corrupted after the machine crashed while the server was running. We rebuilt it from the benchmark's published image and checked that the record counts matched the baseline exactly before recording anything.

## Accomplishments

- A tested end-to-end path from a new lab result to a ready, cited order that a person approves, graded by an external benchmark's own grader.
- A pre-registered series (a pilot, the watch run, a held-out test, a bank of protocols and three fresh-protocol confirmations) in which the pass line and decision rule came before the model output, and the failures are reported.
- 407 of 440 orders right (92.5%) on three protocols the agent had never seen, with no unsafe order.
- Silent misses cut from 33 of 120 runs to 0 on held-out events, with no false orders.
- A second Nemotron that caught 31 of 33 wrong order sets and flagged none of 80 correct ones, for about $0.08 of tokens.
- A gate-catch table that is honest about what gates cannot see.
- A review screen a person can use without reading a log: orders beside the cited lab, a stated reason when nothing was ordered, and nothing written without a click.
- Thousands of agent runs on Token Factory for a small share of the credit.

## What we learned

- The harness mattered more than any check we added: the same model went from 13 to 27 of 30 when only the harness changed. That is why the baseline has to be the strongest realistic one, and why our own pre-registered rule dropped the claim that gates raise task success.
- Gates see structure, not meaning. A wrong patient or a forged citation is blocked every time. A dose ten times too low, a wrong route and a missing paired order pass. The person reviewing the order is the only barrier for those.
- The failure that matters most for a results watch is the silent miss: the agent finishes without ordering. It is not on the worklist, and it reads like "nothing to do". A one-time self-review before finishing removed it on held-out events, which a structural gate could not.
- The form the agent writes orders in decides more than the prompt: both big failures were an order tool that could not say 'twice daily for 2 days' or 'priority routine'. Fixing the tool beat tuning the prompt.
- For fixed, well-known protocols a coded rule is more accurate than a model. The case for the model is a unit adding a protocol as text; across the 10 protocols we tried it ranged from 77% (glucose) and 80% (calcium) to about 98% (the three final-test protocols after the tool fix), so a person still has to check each order.
- Pre-registering before the first model call, and writing down what each result would and would not show, made it easy to report a narrow pass and a weak spot without spin.

## What's next

- **Close the loop on the checker.** The second Nemotron detects wrong order sets. Feeding its findings back to the drafter is untested.
- **Close the meaning gap.** Compare each drafted order with the dose the protocol text computes from the cited value, and require a citation (an order that cites no lab passes today).
- **Test the claim that matters.** Whether a ready-written order beats an order set with an alert is a hypothesis. We have not tested it, and it needs clinicians: do reviewers notice a wrong dose on this screen, and does it save them time.
- **More models and real protocols.** Full runs on Nano and Ultra, and protocols longer than the short demo ones.
- **Before any real use,** authentication, an audit trail and an interface to a real record system. Today it is local-only, has no login, runs on synthetic data, and makes no clinical claims.

## Feedback on Nebius Token Factory, AI Cloud and NVIDIA tools

Written from what happened in this project (the form requires it). Used: Token Factory with Nemotron 3 Super. Not used: AI Cloud, Serverless Endpoints or Jobs.

- **What worked:** the OpenAI-compatible endpoint and native tool calling worked with `nvidia/nemotron-3-super-120b-a12b` with no client changes beyond the base URL and key. Thousands of five-call agent runs cost a small share of the credit, which made it practical to pre-register many tests.
- **Rate limits:** with 36 requests in flight (six protocols at six workers each) the endpoint returned HTTP 429 and a run stopped after five retries. Eight to 24 in flight was fine. A documented concurrency limit and a `Retry-After` value on 429 would let a client back off instead of failing. I do not know whether either exists; I did not find one while building.
- **Nemotron behaviour that mattered:** in some runs the model sent a nested array argument (`dosageInstruction`) as a JSON string instead of an array. A schema check on our side caught it and the model corrected it on the next turn. Stricter argument typing for nested arrays in tool calls would remove a class of retries.
- **Model behaviour we liked:** given a protocol as plain text, it ordered nothing on hold and no-order events in all but a handful of the several thousand runs we made, and it used the retrieved record (an exclusion lab) instead of the number in the prompt.
- **Model choice:** we also tried Nano, Lightning and Ultra on the same job (partial runs, stopped for budget; docs/MODELS_RESULTS.md). Nano missed orders and spent about 52,000 reasoning tokens per run, so it was not cheaper than Super per run; Lightning looped (about 235,000 prompt tokens per run) and failed; Ultra matched Super on one protocol at about twice the calls. Super was the right size for this job.
- **Spend visibility:** the console's usage page breaks cost down by model, which is good, but it carries a "last updated" delay and the balance lagged, so I could not watch spend while a batch ran and the balance fell from \$10.64 to \$4.36 during one experiment. A live balance, or the cost of each request in the API response next to the token counts, would let a client stop itself at a budget.

## Honest limits

- Synthetic benchmark patients. No clinical claims, and no clinician has used it.
- The claimed edge over existing protocol order sets (the order arrives already written, so acting takes one tap) is a hypothesis. Nothing has tested it.
- The demo protocols are short and written from the benchmark's task wording. The renal exclusion value (eGFR below 45) is invented for the demo.
- Drafting was scored on Nemotron Super only. Nano, Lightning and Ultra got partial runs that stopped for budget. One sample per task, 30 pilot tasks and 36 watch runs, so intervals are wide (about plus or minus 15 to 17 points).
- A person has to check each order: 12 of 120 runs with a complete order set still had a wrong dose, duration or time.
- A coded rule script beats the model on accuracy for these protocols. Protocols and graders were designed by model agents, not clinicians. The third confirmation set failed as pre-registered, and its 93% is a post-hoc rescore.

## Built with

python, uv, httpx, fhir, nebius, nemotron, medagentbench

## Links

- Working demo (a read-only recorded scan of the live model; running it yourself is in the README): https://yatsuiii.github.io/medgate/demo/
- Repository: https://github.com/Yatsuiii/medgate
- Demo video (under 3 minutes): [YOUTUBE URL]

## Notes for the form

- New project, started 2026-10-12 during the hackathon window, so no "what changed" note should be needed. Confirm against the rules page before submitting.
- No session or transcript links anywhere in the form, repo or video description.
