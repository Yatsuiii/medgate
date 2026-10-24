# medgate notes (2026-10-12)

## Baseline outputs (contract gate 1)
- Image jyxsu6/medagentbench:latest, 6.89 GB on disk (1.84 GB compressed); container `medgate-fhir` answers `GET /fhir/metadata` about 40 s after start.
- vendor/MedAgentBench/data/medagentbench/test_data_v2.json: 300 tasks, 30 in each of 10 categories; 9 tool definitions (6 GET, 3 POST).
- Task 1_1 (Peter Stafford, 1932-12-29) expects MRN S6534835; the live server returns exactly that patient. All 10 categories' first-task MRNs exist in the live database (tests).
- Only 30 of 300 tasks carry expected answers (`sol`, the task1 lookups). The other 270 are graded by the withheld refsol.py, NOT downloaded (needs the user's explicit approval).

## What reading the reference loop showed (vendor/.../tasks/medagentbench/__init__.py)
1. POST requests are never sent to the server. The loop only json.loads the payload and replies "POST request accepted and executed successfully"; the grader judges POST payloads found in the history. So read-after-write is untestable here and the write gate became a dry-run `$validate` of the payload.
2. A reply not starting with GET, POST or FINISH( ends the task as an invalid action. A re-prompt (arm B1) is a harness fix, reported separately from the safety gates.
3. The server answers `application/fhir+json;charset=UTF-8`, so the reference's exact check `== 'application/json'` fails and the agent receives raw text, not parsed JSON. medgate reproduces this.
4. Defaults: 8 rounds, base http://localhost:8080/fhir/, `&_format=json` appended to every GET.

## `$validate` behaviour (live)
- valid ServiceRequest: HTTP 200, warnings only (narrative recommendation).
- status "bogus": HTTP 400 OperationOutcome with an error.
- Observation without code: HTTP 200 with error "Observation.code: minimum required = 1".
- Validation does not persist anything (tested).

## Arms (frozen in the contract)
A reference loop; B1 = A + format retry; B2 = B1 + payload validation; B3 = B2 + evidence gate. Stop rule on B3 minus A: under 5 points overall or CI includes zero.

## Not done / blockers
- Nebius Token Factory key and model choice (no LLM has been run).
- refsol.py approval and review (grading of 270 tasks).
- Evidence gate currently checks only that referenced record ids appear in what the agent was told or retrieved; it does not check clinical values or doses.
- The validator can reject payloads that the benchmark grader would accept; this must be measured on real model output before B2 and B3 are trusted (false-block rate).

## Where things live now (2026-10-12, moved off the root partition at the user's request)
- All projects are on the Windows drive under /run/media/Yatsuiii/Windows-SSD/work/ with symlinks in /home/Yatsuiii (medgate, mcp-vet, neurovariant, brainconnect-nebius, python-sdk-audit). Venvs were rebuilt there with UV_CACHE_DIR=/run/media/Yatsuiii/Windows-SSD/uv-cache and UV_LINK_MODE=copy.
- The FHIR server no longer runs in Docker. It was copied out of the image to work/fhir-server (app 331 MB, H2 database 4.0 GB) and runs natively: `work/fhir-server/run_fhir.sh` (host Java 27 works; about 30 s to start; port 8080; config copy application_local.yaml points the H2 file at the Windows drive). The Docker container and image were removed, freeing about 10.7 GB on the root partition. To rebuild from scratch: `docker pull jyxsu6/medagentbench:latest` then `docker cp` /app and /data out.
- Tests still pass from the new location: medgate 57, mcp-vet 59.

## The grader (vendor/refsol.py, downloaded 2026-10-12 with the user's approval from the Box link in the benchmark README; gitignored, do not publish)
Read in full before use: plain Python, reads only the local FHIR server, no file writes, subprocess or external network.
- It reads the history as attributes (`i.role`, `i.content`) and `results.result` as a string; medgate needs an adapter.
- `check_has_post` fails a no-write task if ANY agent message contains the text POST, even a POST that a gate rejected. `extract_posts` counts only POSTs answered with "POST request accepted". So gates can correct bad writes and block invented references, but cannot undo an unwanted write attempt.
- Grading is exact: fixed codes (SNOMED, LOINC, NDC), exact urls f"{api_base}ServiceRequest", fixed timestamps (now = 2023-11-13T10:15:00+00:00), dose arithmetic (potassium dose from the last value), required post counts (task9 needs exactly 2 accepted POSTs).

## Phase 2 (2026-10-12): spec gate, grading adapter, runner, statistics
- Gate 1 was redesigned after a measurement. The server's strict FHIR `$validate` rejects payloads the grader itself requires: task 8 (`note` as an object, FHIR wants an array) and tasks 5 and 9 (`route` as a plain string, FHIR wants an object). That is about 90 of 300 tasks. Gate 1 now checks required fields and value types against the benchmark's own tool spec (funcs_v1.json). The one place the spec contradicts the grader (`MedicationRequest dosageInstruction[].route`, spec says object, grader needs a string) is exempted, documented in gates.py and tested. Decided before any model ran.
- Tasks 2 to 10 all name the patient MRN in the question text, so the evidence gate (B3) can only fire on a mistyped or invented id. Expect B3 close to B2; do not oversell it.
- The grading adapter (src/medgate/grade.py) loads vendor/refsol.py, wraps history as attributes, and treats a run with no FINISH result as incorrect, as the reference harness does. Verified with scripted oracle agents on tasks 1, 2, 3 and 8; grader-correct task 3 and 8 writes are never blocked by any gate configuration.
- 104 tests (pure, live against the native server, grader, runner, stats, CLI), ruff, format and pyright strict clean. Mutation checks: disabling the required-field check, removing the route exemption, making the grader always pass, removing the unfinished-run rule (a test gap found and closed), one-sided McNemar and not counting rejected POSTs each make tests fail.

## Running the experiment once there is a key
1. Start the server: `/run/media/Yatsuiii/Windows-SSD/work/fhir-server/run_fhir.sh` (about 30 s, port 8080).
2. `export UV_CACHE_DIR=/run/media/Yatsuiii/Windows-SSD/uv-cache UV_LINK_MODE=copy`
3. For each arm in A B1 B2 B3: `uv run python -m medgate run --arm ARM --model MODEL_NAME --base-url URL --key-file ~/.nebius_key --out runs/ARM.jsonl --pause 1` (resumable; rerun the same command after any interruption).
4. `uv run python -m medgate compare runs/A.jsonl runs/B3.jsonl` (also A vs B1 and B1 vs B2 to attribute the gain).
Needs from the user: the Nebius Token Factory base URL, the exact Nemotron model name, and the key in ~/.nebius_key (not yet provided as of 2026-10-12).
Rough cost, unverified: 300 tasks x 4 arms, about 14k input tokens per task, so roughly 17M input tokens plus small outputs; price depends on the model chosen.

## Phase 3 (2026-10-14): submission package without a model run
LICENSE (Apache-2.0), full README, docs/SUBMISSION_DRAFT.md, docs/DEMO_SCRIPT.md, docs/SUBMISSION_CHECKLIST.md. Every result is a bracketed placeholder. Blocker unchanged: Nebius Token Factory key, base URL and model name. Nothing committed or published.

## Phase 4 (2026-10-14): baseline screen, verdict PIVOT
docs/BASELINE_SCREEN.md. MedAgentBench v2 (PSB 2026) reached 91.0% with GPT-4.1 using structured tools, a typed finish tool, a calculator and a planning prompt (98.0% with memory); its code has no license. Symbolic guardrails (arXiv 2604.15579, Apache-2.0) already show 0% unsafe on MedAgentBench with GPT-5 at success 0.67 vs raw 0.64. Medmarks (MIT) ran open models on a v2 wrapper. medgate's arm A is therefore the weakest baseline on record; B1 and B2 are weaker versions of v2's fixes. Redesign proposed (v2-class arm A' plus gates, Nemotron pilot), awaiting the user's decision.

## Phase 5 (2026-10-14): strong baseline arm T and gated arm TG, no model run
- Data check that set T's search defaults (live server, the 180 tasks in categories 4-7, 9, 10): the server pages 20 results by default, in no date order; 74 of 180 tasks have more than 20 observations for their code and 14 have more than 200 (largest: K 1261, GLU 633). `_count=5000` returns everything; `_sort=-date` works. A raw observation is about 1,230 characters, so unfiltered results cannot fit in a prompt. At most 13 observations fall inside any task's 24-hour window (task6_13).
- Decisions from it, before any model output: T's searches expose the standard FHIR `_sort` and `_count`, `_count` defaults to 200 (MedAgentBench v2's cap), the prompt says results are unordered and how to sort and filter, and a result longer than 60,000 characters is cut with a note on how to narrow it. The create tools fill `resourceType` when the model omits it (the tool targets one resource). The spec-grader route conflict is typed as a string in the medicationrequest_create schema.
- Grader view: every tool call is mirrored into `history` as the reference protocol's text action, so refsol.py scores T and TG exactly like A; a create call is a POST attempt whether or not a gate accepted it; the model's free text is kept in `transcript` only.
- Tests: 187 pass (104 before plus 58 pure tool tests and 25 live grader and CLI tests). Scripted oracle agents are graded correct by the real grader in both T and TG on tasks 1, 2, 3, 5 (low and normal magnesium), 8, 9 and 10 (due and recent), with zero gate rejections; an off-by-one age and a create call on a read-only task grade incorrect. Mutation checks caught: tool naming without the qualifier, a calculator that reaches builtins, a disabled read-side evidence check, and an unrelaxed route type. ruff, ruff format and pyright strict are clean.
- Pilot protocol drafted in docs/PILOT_PREREG.md (30 tasks, arms A and T, nvidia/nemotron-3-super-120b-a12b on the NVIDIA API). Not frozen: sampling and thresholds await the user. No model, key or API was used.

## Phase 6 (2026-10-14): a stronger T, no model run
- Searches now fetch every match (`_count=5000`, the grader's own fetch size), sort by the resource's clinical date (newest first by default), strip FHIR boilerplate (meta, narrative, URL-valued systems, duplicated unit codes; Codings and References become strings) and show as many compact JSON lines as fit in 60,000 characters, after a count line that says how many matched and how to see the rest. `_sort` and `_count` now act on the fetched results. src/medgate/results.py.
- Measured on the 180 read tasks (categories 4-7, 9, 10), against the Phase 5 default view (raw, 200 unsorted, clipped), which assumes the model does not sort on its own: that view missed the newest reading on 20 tasks and part of the last 24 hours on 22. The new view shows the newest reading first and every reading from the last 24 hours on all 180 (live test). Size: full raw bundle median 10,470 and max 1,554,527 characters; Phase 5 view median 10,469, max 60,098; new view median 2,276, max 60,027.
- Finish check: an answer with a number written as text ("4.2", "-1") or with a unit ("4.2 mg/dL") gets one nudge; the next finish is accepted as it stands; counted as a format retry. Dates, MRNs, "118/77 mmHg" and plain text are not nudged.
- Data quirk found: the spec tells agents to search conditions with category=problem-list-item, but no condition on this server has a category, so that search returns nothing. No benchmark task searches conditions.
- Bugs caught by the new tests before any model run: compaction treated a lone {"code": {...}} as a Coding.
- 218 tests pass (31 new). Mutation checks caught: unsorted results, compaction dropping values, the finish check disabled. ruff, format and pyright strict clean.

## Phase 7 (2026-10-14): GPT-4.1's published runs (docs/GPT41_BASELINE.md)
- Source: the MedAgentBench v2 repository's outputs (no license; downloaded to work/gpt41-runs, outside this repository). Original-task set: GPT-4.1, reference loop, temperature 0.
- medgate's grade() agrees with the published grading on 300/300 runs: the first check of the adapter on real model conversations.
- GPT-4.1 on the reference loop: 175/300 (58.3%); task7 0/30, task9 0/30, task10 3/30. 96 of 125 failures are answer format (73 sentences, 23 objects or nested lists); 33 failures read only a partial page; 30 never searched the code the task gives for looking up results (task9 searched the LOINC ordering code). On v2's new tasks the same loop scored 0.643 (recorded, not re-graded).
- Traps: task9 normal potassium, no order on 29/29 but only because it never found the values; task10 no A1C, ordered on 8/13 unprompted.
- Script: analysis/gpt41_baseline.py, identical output on two runs.

## Phase 8 (2026-10-14): Phase 7's lessons applied to T
- The finish check (tool_agent.answer_problems, now public) also nudges sentences (four or more words) and answers holding objects or lists, once, never blocking. Replayed over GPT-4.1's 300 final answers it catches all 96 format failures; it would also nudge 76 correct answers, all on tasks whose answer the grader ignores (task3 30, task8 30, task5 no-magnesium 16), each costing one round, not the answer.
- An empty search now reads "0 results." plus a hint to try the task's other codes or parameters (GPT-4.1 failed 30 tasks searching the ordering code). Live test: searching potassium by its ordering code returns the hint.
- 222 tests pass; the sentence-rule mutation is caught; ruff, format and pyright strict clean.

## Phase 9 (2026-10-14): the product core, review before the chart
- Orders cite their evidence: the MedicationRequest and ServiceRequest create tools offer FHIR reasonReference, and the prompt asks for it when an order follows from a retrieved record. TG's existing evidence gate verifies citations (a forged Observation/999999999 is rejected). Cited oracle runs still grade correct on tasks 5, 9 and 10 in T and TG.
- src/medgate/review.py: proposals(history, fhir) turns every attempted write into a Proposal (payload, gate findings, cited records read back in compact form); commit() refuses proposals with findings unless overridden, converts to conformant FHIR (route text to CodeableConcept, ServiceRequest note object to list), writes, reads back and reports dropped paths.
- Finding: the FHIR server accepts a MedicationRequest whose route is plain text (the shape the benchmark grader requires) and silently stores it without the route (HTTP 201, no error). A ServiceRequest note object is coerced into a list. Test: test_the_server_silently_drops_a_route_written_in_the_benchmark_shape.
- Live tests delete what they create (HAPI soft delete: searches and counts return to baseline, deleted versions stay in history). Baseline counts: MedicationRequest 21991, ServiceRequest 0, Observation 563426.
- 240 tests pass; mutations caught: a run that writes, a commit that ignores findings, a commit that skips the FHIR conversion. ruff, format and pyright strict clean.

## Phase 10 (2026-10-14): the review screen
- `medgate serve` (src/medgate/web.py, review_page.html): a local page over arm TG. Ask, watch steps, review each proposed write beside its cited records and gate findings, approve to write (conformant FHIR, read back). Standard-library HTTP server on 127.0.0.1, one self-contained page, no new dependencies. Replay mode (demo/replay_potassium.json, built by demo/make_replay.py from task9_3, patient S6550627, newest K 3.1) runs scripted turns and the page labels it.
- Verified in Chrome: the page renders, the replay run shows plan, search ("46 results, newest first."), calculator, two orders citing Observation/330934 (K 3.1 mmol/L), gates passed; approving the medication order wrote MedicationRequest/786026, read back with route {"text": "oral"} and the citation intact; it was then deleted and counts returned to 21991/0/563426.
- The browser check exposed a false message: the agent was told "Accepted: the record was created." although nothing is written before review. Now "Accepted: the write is recorded." (dated deviation in the Phase 10 contract; arms T and TG see this text).
- Test bug fixed: the FHIR server reuses identical searches for a while, so a count right after a write showed the old number; live count checks now send Cache-Control: no-cache. Re-checked: no leftover resources.
- 251 tests pass; the mutation letting /api/commit write a rejected proposal is caught; ruff, format and pyright strict clean.

## Phase 11 (2026-10-14): the results watch, aimed at a documented pain
- User's direction: solve people's pain; chose "results watch" with literature-only evidence. docs/PAIN.md: Callen 2012 (6.8% to 62% of lab tests not followed up; hyperkalaemia harm), Murphy 2016 (76.9 notifications a day, 20.2% test results, about 67 minutes estimated), Gopalsami 2023 (nurse protocol: 344 to 112 minutes result to dose) checked on primary pages; two further figures labelled as unchecked summaries. The edge over existing protocol order sets is stated as an untested hypothesis.
- src/medgate/watch.py: per ward patient and protocol, the newest covered result inside the window (results after "now" ignored; a failed search raises). The agent applies the protocol text; nothing in code decides abnormality. case_for() puts the protocol in the context and the result in the question.
- Screen: results-watch view (worklist sorted by action, summary line, same review cards); /api/watch; /api/run renamed /api/ask; replays keyed by task id (demo/replay.json, 10 watch runs plus the ask run), ward in demo/ward.json (6 benchmark patients: K 3.1, 3.9, 3.8, 4.0, 3.7, 4.2; MG 2.0, 1.8, 1.9, 2.0), built by demo/make_replay.py.
- Measured by the benchmark: 8 of the 10 demo events belong to benchmark patients of the matching task (K to task9, MG to task5); all 8 scripted watch runs are graded correct by refsol against the benchmark's own cases, and every order cites its triggering result.
- Verified in Chrome: "10 new results checked. 3 need action: 4 orders drafted for review."; approving the S3084624 magnesium order wrote MedicationRequest/786055 (route IV, 1 g over 1 h, citing Observation/344826), read back whole, then deleted; counts back to 21991/0/563426.
- 266 tests pass; the window-ignoring detection mutation is caught; ruff, format and pyright strict clean.

## Phase 12 (2026-10-15): pilot readiness, frozen before any model call
- OpenAiCompatibleLlm now survives real-endpoint behaviour, tested over real HTTP against a local fake chat-completions server (tests/test_wire.py): 429, 5xx and dropped connections retry up to 5 attempts (Retry-After honoured, otherwise 2, 4, 8 s, at most 60 s) then stop with LlmError; other 4xx stop at once and never show the key; a 200 without choices is an error; null content is an empty reply (it used to become the text "None"); text before a closing think tag is dropped; non-JSON tool arguments reach the agent, which returns an error to the model. New option --max-tokens (pilot uses 8192).
- Arms A and T each run a task over HTTP into a graded record; a run that dies midway resumes without repeating finished tasks.
- Mutation caught: dropping the sampling parameters from the request fails test_the_request_carries_model_sampling_tools_and_key.
- docs/PILOT_PREREG.md frozen 2026-10-15 with sampling temperature 1.0, top_p 0.95, max_tokens 8192 and the drafted thresholds. Model id is still UNVERIFIED against the user's catalog; a corrected id is a dated deviation.
- Pilot prereg sha256 (before any model call): d79a8efdbdc381eb89002fe2ca62b077ce47aa76fce74814cda96c5d12c10ad7

## Phase 13 (2026-10-15): the demo grows an exclusion; the submission drafts are rewritten
- Demo magnesium protocol gains one invented exclusion: check the newest eGFR (code EGFR) and hold magnesium for pharmacist review below 45. Ward now 7 patients (S0722219 added: Mg 1.7, eGFR 41, a task 9 patient with no task 5 case), 12 new results; low-magnesium scripted runs search eGFR first (2 still order, 1 holds). 9 of the 12 events belong to a benchmark patient of the matching task; all 9 scripted runs graded correct by refsol.
- The worklist now shows the agent's last note on events that order nothing, so a hold is visible instead of reading as "protocol calls for no order". Verified in Chrome in replay mode; nothing written; counts 21991/0/563426.
- Mutation: restoring the old replay file fails 3 live tests.
- docs/SUBMISSION_DRAFT.md and docs/DEMO_SCRIPT.md rewritten around the results watch (bracketed placeholders for everything a model run fills); docs/SUBMISSION_CHECKLIST.md updated. The potassium protocol is unchanged, so the frozen pilot is unaffected (the pilot uses the benchmark's own tasks, not the demo ward).
- Known gap: held events sort among the quiet ones in the worklist.

## Phase 14 (2026-10-16): what the gates catch, measured without a model
- analysis/gate_catch.py breaks one thing at a time in the correct scripted potassium run and runs it through TG and the review step; results in docs/GATE_CATCH.md. Structure errors (wrong patient, forged or unretrieved citation, missing field, wrong value type) are blocked 5 of 5. Meaning errors (dose ten times low, wrong drug, wrong route, wrong recheck day) reach the worklist unflagged 4 of 4; an uncited order also reaches it and the benchmark grader marks it correct (a gap).
- The mutations are hand-written, so this shows what the gates can see, not how often a model errs. It supports the framing that the review screen, not the gates, is the barrier for meaning errors.

## Phase 15 (2026-10-22): live mode tried end to end; polish for a reviewer
- demo/fake_model.py: an OpenAI-compatible endpoint that replays the demo's scripted runs over HTTP with a delay per reply, so the screen's live mode (a model behind it) runs without a key. Its output is scripted and its model name shows on the page.
- Found by trying it: the watch ran every agent run one after another inside one request. At 1 s per model call a 12-result scan took 32.5 s with one request in flight; at the 10 to 20 s per call a large reasoning model may take (assumption, unmeasured) that is 5 to 11 minutes of "Checking...". Now four runs go at once (web.WATCH_WORKERS): 9.3 s, four in flight, same 12 events and 4 cited orders as the replay.
- Found by reading: a model-endpoint failure took the whole worklist down and was labelled "FHIR server". Now the failing result stays on the worklist as "model endpoint failed: ...", counts as needing a person, and sorts to the top; the others complete. The scan shows elapsed seconds.
- tests/test_live_mode.py drives the screen over HTTP against the fake endpoint: parallel runs, failure isolation, the ask view. Mutations caught: one worker; model errors escaping.
- Verified in Chrome in live mode at 2 s per reply: timer counted, "12 new results checked. 3 need action: 4 orders drafted for review."; approving the S3084624 magnesium order wrote MedicationRequest/786256 (route IV, 1 g over 1 h, citing Observation/344826), read back whole, then deleted; counts 21991/0/563426.
- Fresh-copy check: the files `git add .` would take (no vendor, venv or caches), copied to a clean directory with the benchmark linked in: `uv sync` works, 198 tests pass without the server and 288 with it, and the README's replay command serves the page with 12 events and 4 orders. Copy deleted afterwards.
- README now leads with the results watch, the gate-catch result and the frozen pilot; the old four-arm design is kept below as the original Phase 1 plan. Removed third-party security-sensitive details from the public docs (Devpost draft, GPT-4.1 baseline doc, these notes); the record is kept privately.
- Not changed: .claude/ (session contracts with local paths) would be included by `git add .`; whether to publish it is the user's call.

## Phase 16 (2026-10-22): the pilot report, so the decision rule is applied mechanically
- `medgate pilot runs/pilot_A.jsonl runs/pilot_T.jsonl` (src/medgate/pilot.py): per-arm and per-category correct counts, paired discordant counts, the pre-registered threshold decision on T's count (27 or more / 18 to 26 / 17 or fewer), T's failures listed for hand classification into the 8 frozen classes. It refuses to score when a pilot task is missing, duplicated or from another arm, or when the arms ran different models. It reads run files only; the frozen design and hash are unchanged. A test checks the 30 task ids against the list frozen in docs/PILOT_PREREG.md.
- Mutations caught: threshold 27 to 28; missing-task check removed.
- Searched the Gmail inbox the connector can read (Promotions, Updates, Primary, trash; sender and keyword searches for Nebius, NVIDIA, Tavily, Devpost, credits, $25) on 2026-10-22: no email offering $25 credits. The only Nebius mail is newsletters; the AI Builder Program (24 Sep newsletter) advertises "$400+ in credits and discounts" with no code in the email. Spam is not searchable through the connector.

## Deviation 1 (2026-10-22, before any model call): the pilot runs on Nebius Token Factory, not the NVIDIA API
- docs/PILOT_PREREG.md (frozen, sha256 d79a8efd...10ad7, file unchanged) names the NVIDIA API endpoint (https://integrate.api.nvidia.com/v1) and ~/.nvidia_key as development-only, with the hackathon run to follow on Nebius. The user now has Nebius Token Factory working (two $25 promo codes applied, balance $59.00, key in ~/.nebius_key), so the pilot runs there directly: base url https://api.tokenfactory.nebius.com/v1/, key file ~/.nebius_key.
- Model id nvidia/nemotron-3-super-120b-a12b is VERIFIED to exist on the account (GET /v1/models, HTTP 200, 27 models). Everything else in the prereg is unchanged: same 30 tasks, arms A and T, temperature 1.0, top_p 0.95, max_tokens 8192, thresholds, failure classes.
- ASSUMPTION, not checked: Nebius serves the same weights as NVIDIA's hosted endpoint; precision or serving details may differ. The results are for this model as served on Nebius, which is what the submission must use anyway.

## Pilot started 2026-10-22 (after Deviation 1; no earlier model output exists)
- A one-task smoke run (arm T, task1_13, frozen sampling) preceded the pilot: 2 rounds, well-formed tool calls, correct. It is used as arm T's task1_13 result in runs/pilot_T.jsonl, so that task was sampled once, not twice. Nothing was discarded.
- Commands: the frozen ones in docs/PILOT_PREREG.md with the Nebius base url and ~/.nebius_key, `--pause 2`. Reported with `uv run medgate pilot runs/pilot_A.jsonl runs/pilot_T.jsonl`.

## Pilot result (2026-10-22): arm A 13/30, arm T 27/30; the pre-registered rule drops the gate-success claim
- Full write-up: docs/PILOT_RESULTS.md. Same model, only the harness changed: 13 to 27 correct (only T correct 15, only A correct 1, McNemar exact p = 0.0005). T got 27, exactly the "27 or more" line, so by the frozen rule there is little room for gates and the gate-success claim is dropped. No claim of parity with GPT-4.1's 91.0% (different harness, 30 tasks).
- T's failures, three independent readers each then a vote: task1_25 Retrieval (3 of 3; full name put in the given field, no retry), task3_16 Payload (3 of 3; bare MRN as subject reference), task6_12 Retrieval (2 of 3; the FHIR server's date filter with a +00:00 offset returned 2 of 4 in-window records).
- Findings, not acted on because the pilot is frozen: the server-side date filter drops in-window records when the time has an offset (the same query without an offset returns all 4); the existing gates, arm T's and TG's, do not catch a reference without its resource-type prefix.
- Cost: not measured per run. Nebius balance to be read from the console after the watch run (it was $59.00 before the pilot).

## Watch run pre-registration frozen (2026-10-22), before any model run of the watch
- docs/WATCH_RUN_PREREG.md sha256 5b41c7ace06a8fc749c8b4c6e42b4920fa5f2f88a530251c221435f05c455d79. 12 events, 3 runs each, arm TG, same model and sampling as the pilot. Supports: at least 22 of 27 graded runs correct, no order on the 9 no-order runs, every order cites its result. Fails: 13 or fewer of 27.

## Watch run result (2026-10-22), under docs/WATCH_RUN_PREREG.md (sha256 in the entry above)
- runs/watch_TG.jsonl: 36 runs of arm TG, Nemotron 3 Super on Nebius, same sampling as the pilot. Graded correct 23 of 27 (supports at 22 or more), orders on the 9 must-order-nothing runs 0 (needs 0), every order cites its triggering result (true). By the pre-registered criteria: SUPPORTS the product claim, narrowly (23 against a bar of 22; 95% interval about plus or minus 15 points).
- The 4 incorrect runs: S6550627 K (low potassium 3.1) drafted no order in 2 of 3 runs; S3084624 MG (1.8) no order in 1 of 3; S6542579 MG (1.9) 1 g order drafted in 3 of 3 runs but graded correct in only 2 of 3.
- Defect in my script, disclosed: it did not save transcripts, so the original failing runs cannot be read. Nothing about the verdict depends on this. A separate diagnostic run (runs/watch_diag.jsonl, not part of the criteria) re-samples only those three events with transcripts saved, to find why.

## Watch diagnostic (2026-10-22), not part of the pre-registered criteria
- runs/watch_diag.jsonl: 24 runs re-sampling only the three events that failed (S6550627 K, S6542579 MG, S3084624 MG), 8 each, transcripts saved. Correct 5/8, 5/8, 8/8. All 11 runs per event: 6/11, 7/11, 10/11. Chosen because they had failed, so not an unbiased estimate.
- The 6 failing runs, three independent readers each, unanimous: 3 missed orders (K 3.1 finished with no order; MG 1.9 twice finished after a correct eGFR lookup without ordering, treating the top of the 1.5 to 1.9 band as outside), 1 incomplete order set (paired stat potassium never created), 2 payload errors (wrong time fields; duration rate omitted). Full write-up: docs/WATCH_RESULTS.md.
- Cost: the whole day's model use (pilot, watch run, diagnostic) $0.33 on Nebius, absorbed by the $1.00 trial credit; the $59.00 balance untouched.
- Bug found and fixed on the way: grading from several threads at once could load the grader half-built (src/medgate/grade.py, now serialized by a lock; the test fails without it).

## Held-out test pre-registered (2026-10-22), before the baseline run on it and before any fix is chosen
- docs/HELDOUT_PREREG.md sha256 28ef52fcd6f9fe368d5d92bc7cf9b2481a8c90ab438445a0996bb07d50334fd3. Held-out ward runs/heldout_ward.json (44 events from 27 patients not on the demo ward: 12 need orders, 1 hold, 31 need nothing; built by analysis/heldout.py, seed 0). Baseline vs treatment, 5 runs per event each. The change works if silent misses at most half the baseline, false orders at most baseline plus 3, payload accuracy no more than 5 points lower; fails above 75% of baseline misses or +8 false orders; inconclusive if the baseline has fewer than 6 misses per 60 runs even after one extension.

## Held-out addendum frozen (2026-10-22), before any run on the held-out set
- docs/HELDOUT_ADDENDUM.md sha256 9bb8a1f67faea189c402534ddad4ed135340e01682067691276a1cb11e75b779. Treatment: the finish-time review (GateConfig.finish_review, preset gates.WATCH); REVIEW text sha256 c51a6b3ebce0406d34c49d677f386629885e82d96c4df4376245ee8661e979b1; held-out ward file sha256 9a8c64aeb5a7d47ea83ed180b2f4cbd9314fed7e4382baad1e1b7d02009dd56c. 10 runs per needs-orders or hold event, 4 per need-nothing event, both arms side by side. Stricter: any order on the hold event, or more unfinished runs than the baseline, fails the change. Built after a three-design panel with critics; the screen default is unchanged until this passes. Also fixed on the way: the no-order status on the page said "Checked: the protocol calls for no order." though nothing was checked; it now says "No order drafted. The agent's reason is not checked."

## Held-out run: crash and rerun (2026-10-22)
- The baseline arm completed (254 runs). The audit arm crashed after 24 runs: my oracle (analysis/heldout_run.py) assumed a dosage was an object and the model once wrote a string (an analysis bug, not an agent or product bug). Fixed so a malformed payload counts as inaccurate and cannot crash a run (tests/test_heldout.py). The 24 partial audit rows are kept in runs/heldout_audit_crashed_partial.jsonl and are not used. The audit arm is rerun completely from scratch, so no run is replaced by a different sample of an unlucky one. The baseline needed no change: it had no crash and the fix does not change judgments on well-formed payloads.

## Held-out result (2026-10-22): the finish-time review works by the pre-registered criteria
- docs/HELDOUT_RESULTS.md. Silent misses 33/120 (baseline) to 0/120 (review); false orders 0 and 0 in 134 runs each; hold event 0 orders in 10 runs each; unfinished 0 and 0; end to end complete and accurate 74/120 to 108/120; calls per run 1.98 to 3.27. All 12 events improved. Rubber-stamp check passed (28 of 28 runs with no order before the review ordered after it). Side effect not in the criteria: 7 of 120 review runs drafted more orders than needed (0 in the baseline), mostly re-written versions of the same order. Cost of the whole held-out run is in the Nebius ledger (read after).

## Review made the watch default; superseded marking (2026-10-22)
- WATCH_CONFIG in src/medgate/web.py is now gates.WATCH (arm TG plus the finish-time review), because the held-out experiment met its pre-registered criteria. The ask view stays on plain arm TG. Arms A, T and TG are unchanged and reproducible.
- review.mark_superseded: a draft is marked superseded when a later draft in the same run has the same resource type and code and both passed the gates (nothing removed). The page mutes it, warns that approving both would order twice, and counts only current orders. Evaluated offline on the 254 saved review-arm runs: the 7 runs that had too many orders show exactly the expected number of current orders; payload accuracy unchanged (108 of 120).
- demo/replay.json rebuilt: watch runs end with a second finish that repeats the reason (so the page shows e.g. the eGFR hold reason); the ask run is unchanged. Verified in Chrome with a temporary replay containing a duplicate order: summary "12 new results checked. 3 need action: 4 orders drafted", card marked superseded.
- Full suite, ruff, format and pyright strict pass with the server up.

## Cost (2026-10-22, read from the Nebius console after the held-out run)
- All model use today (pilot, watch run, diagnostic, held-out baseline and review arms, about 600 runs): consumption $2.67, covered by the trial credit, which is now used up. The $59.00 balance from the two promo codes is untouched; later usage draws on it before the card.

## Order-set baseline (2026-10-22)

- docs/RULESET_PREREG.md sha256 7a57873deb7330fea111f98953d35064e50ea2fc0be909cd1f9e343c5112537b, frozen before the script was written. B1 = hand-coded rule script on the 44 held-out events, judged by the same judge as the agent. B2 (order set with an alert, as people use it) is untestable without clinicians and is reported UNKNOWN.
- Result: rule script 12/12 accurate, 0 misses, 0 false orders on the 44 held-out events, 26 rule lines. Agent with review 108/120 (90%). Prereg verdict: the script matches or beats the agent. Remaining claim, no code per protocol, untested. B2 UNKNOWN. docs/RULESET_RESULTS.md, analysis/ruleset_baseline.py.

## Third-protocol test (2026-10-23)

- docs/THIRD_PROTOCOL_PREREG.md sha256 31d5da8efd50ec8319d2e08e6ca7f822ae7b0974b4bb56d125fd5afc39cfb9af, frozen before the ward, oracle, judge or script existed. Product frozen at commit f2b0ccb (src/ unchanged; tool_agent.py sha256 59f79daed2c1977a..., gates.py 3f3af0409dc40c9e...). New protocol: calcium with an albumin exclusion and a recheck 6 hours after the order. Supported if end-to-end correct >= 90% on needs-orders runs, <= 5% orders on hold runs, <= 2 false orders; fails below 90%.
- Result (2026-10-23): agent end to end 64/80 = 80% (bar 90%), 1 miss, 5/100 orders on holds (at the 5% bar), 0 false orders on 56 need-nothing runs, 3.94 calls per run. Rule script 8/8. FAILS the prereg: "no code per protocol" dropped as a selling point. 9 of 15 wrong payloads wrote the rate as 1 g/h, clinically equivalent but not what the judge required; with it accepted 73/80 (post-hoc, not the verdict). docs/THIRD_PROTOCOL_RESULTS.md, analysis/third_protocol.py, runs/third_agent.jsonl. Cost: see Nebius console. No src/ change made.

## Protocol bank (2026-10-23)

- Built by a workflow of 8 designers and 8 blind checkers (analysis/protocols/p_*.py): oracle (needs), judge (accurate) and rule script (rule_payloads) per protocol; the checkers derived expected orders by hand from the text alone (14 patients each) and mutation-tested each judge, and fixed real judge bugs (extra or duplicate orders were accepted, empty list for a hold was rejected). Troponin dropped (3 events need orders, bar is 6). Rule scripts score 100% on every bank ward. bank_run.py adds a wrong-patient check the judges cannot make.
- Split, fixed before any model run on the bank: DEV (used to find and fix problems) = sodium, glucose, thyroid (a sodium-screen variant), hemoglobin. TEST (frozen, no model run and no edit until the final test) = creatinine, inr, ldl (oral metformin by glucose tier with an ALT hold). I have read the TEST protocol texts; the fixes must be generic and may not be shaped to them. TEST module files sha256 (first 16): 08fd42a2408ba964  p_creatinine.py;744d1077a09499c4  p_inr.py;a45a0e0c0b5ce42c  p_ldl.py;
- Thresholds in glucose were moved up to 85 to 90 mg/dL because the data has no glucose below 73; it is not clinically realistic hypoglycemia, the shape is what is tested.
- Dev baseline v1 (current product, benchmark tool spec, all drafted orders judged): sodium 0/151 accurate (the order tool had no field for frequency or duration, so the protocol could not be written), glucose 42/73 (18 of 31 failures were extra orders left by the review step), thyroid 96/96 with 1 false order, hemoglobin 95/104. Files runs/bank/*_watch.jsonl. Fixes made before any test run, both generic: tasks.watch_functions adds FHIR dosage timing (frequency, period, boundsDuration) to the watch's order tool only (benchmark arms unchanged; tests/test_watch_functions.py), and bank_run judges the current set (superseded orders excluded), the set a clinician is asked to approve, reporting the superseded count.
- DEVIATION (2026-10-23): I ran `ruff --fix` and `ruff format` over analysis/protocols/, which also rewrote p_creatinine.py and p_ldl.py (p_inr.py unchanged), before any model run on them. Lint and formatting only; I rebuilt both wards (byte-identical to before) and both rule scripts still score 100%. The TEST module hashes are therefore now: p_creatinine 5ab5988d823d5bcd, p_inr 744d1077a09499c4, p_ldl 9de129ea4866efde (first 16 hex); the earlier ones are superseded. No test judge or oracle may change after this point except for a judge bug class found on DEV, disclosed here first.
- Dev judge bugs found by looking at v1 to v3 results: plain-text route rejected (p_sodium), duration written as timing.boundsDuration rejected (p_glucose). Lesson: a judge must be run on payloads in the shape the agent's tool produces before the model run. TEST judges checked for those two classes before the final test.

## Where things stand (2026-10-23, paused: user's battery died)

- Dev v3 (current product, tool timing field, current-set scoring, fixed judges): sodium 148/151, thyroid 95/95, hemoglobin 100/100, glucose 43/73 (real omissions: no route, no duration, malformed time). Files runs/bank/*_v3.jsonl.
- Built after that, behind flags (benchmark arms and old results unchanged): gates.WATCH_CHECKED = WATCH + field-by-field review (tool_agent.FIELD_CHECK) + ISO time gate (gates.time_problems). Tests, ruff, pyright clean.
- Dev v4 (config `checked`) was started in the background: runs/bank/{glucose,sodium,thyroid,hemoglobin}_v4.jsonl, log in the scratchpad dev_v4.log. If the machine went down, it is resumable: rerun the same `bank_run.py run NAME --config checked --out runs/bank/NAME_v4.jsonl ...` commands (already-done runs are skipped).
- Next: compare v4 with v3 on dev; then write the final-test prereg (TEST = creatinine, inr, ldl; arms watch vs checked vs rule script; bars written before the run), freeze, run, report whatever comes out. Also still open: add the baseline and third-protocol results to README and the Devpost draft; demo recording; nothing is committed or pushed.

## Final bank test (2026-10-24)

- Dev v4 (checked) vs v3 (watch): accurate runs of those needing orders, 406/432 (94%) against 386/432 (89%); glucose 62/80 against 43/80; misses 8 against 5; 3 false orders on hold events against 0. runs/bank/*_v3.jsonl, *_v4.jsonl.
- docs/BANK_PREREG.md sha256 b391507df5eeef3cce32fda121f796611c833337affe76461914df0d45001ab2, frozen before any model run on creatinine, inr, ldl. Arms watch vs checked, 484 runs each. p_inr.py changed after the split (IV duration as boundsDuration accepted; judge bug class from dev), new hash 116b1e76012755a4.
- Typo note: docs/BANK_PREREG.md and the heading above date the freeze 2026-10-24; the actual date was 2026-10-23 (system clock). The file is left unedited so its hash stays valid.
- FROZEN RESULT (docs/BANK_PREREG.md): pooled end to end, watch 110/256 (43%), checked 110/256 (43%): FAILS (floor 85%). Per protocol (watch / checked): creatinine 56/56 / 56/56, inr 54/56 / 50/56, ldl 0/144 / 4/144. Hold orders 0/120 / 1/120, false orders 0/108 / 0/108, misses 1 / 2, 4.13 / 4.11 model calls per run. The fixes are NOT credited (equal pooled). Cause of the ldl collapse: the protocol text requires "priority routine" on a medication order and the benchmark's MedicationRequest tool has no priority field (ServiceRequest has one), so the requirement was unachievable by the tool; the same class as sodium's missing frequency on dev. Not a judge bug.
- Follow-up, labelled post-hoc (found on TEST, so it cannot count as a clean test): tasks.watch_functions gains the standard FHIR MedicationRequest.priority; ldl rerun for both arms into runs/bank/ldl_final2_*.jsonl, judge unchanged.
- Follow-up result: ldl rerun with MedicationRequest.priority in the watch tool, 144/144 for both arms, 0 false and 0 hold orders. Pooled with frozen creatinine and inr: watch 254/256, checked 250/256. Labelled post-hoc. docs/BANK_RESULTS.md, analysis/bank_run.py, analysis/protocols/. Prompt-level fixes (field check, time gate) not credited on test; the tool-schema fixes are what mattered.

## Clean confirmation (2026-10-23)
docs/CONFIRM_PREREG.md sha256 7db3bfb196601935f6beb26db76306c445332cfb7ab832cf64e1b9290e02c6bb, recorded before any model run on potassium_iv, magnesium_tiers, anemia_iron.
Confirmation result (2026-10-23): CAUTION. watch pooled 332/376 = 88.3% (potassium_iv 124/144, magnesium_tiers 115/136, anemia_iron 93/96), 0/24 hold orders, 0/108 false orders; checked 337/376 = 89.6%. Bar for SUPPORTED was 90%. See docs/CONFIRM_RESULTS.md.

## Second clean confirmation (2026-10-23)
docs/CONFIRM2_PREREG.md sha256 66da6b7ad6444611acce1416a9bb4c6c07533fb6a7e297bb48455dac5eed1a17, recorded before any model run on sodium_high, phosphate_oral, lab_pair_urgent. Fix made before it: watch order tool requires route and dose (tasks.py). Dev re-run of the first confirmation protocols with the fix: 361/376 = 96.0% (development, not a test).
Second confirmation result (2026-10-23): SUPPORTED. watch pooled 407/440 = 92.5% (sodium_high/BUN 73/88, phosphate_oral 55/56, lab_pair_urgent 279/296), 0/52 hold orders, 0/108 false orders. See docs/CONFIRM2_RESULTS.md.

## Third clean confirmation (2026-10-24)
docs/CONFIRM3_PREREG.md sha256 8b02998700294e6270411bddadd35a0c5d83eabe9c7317fbbc2642dd7cad7416, recorded before any model run on two_drugs_one_lab, clock_time_recheck, drug_plus_stat_lab. Change before it: a second finish-time review when an order is written after the first (tool_agent.py). Dev re-run of the six earlier protocols with it: 776/816 = 95.1% (development, not a test); the WBC run was interrupted by a 429 and a power loss and resumed from saved rows.
Third confirmation result (2026-10-24): FAILS as pre-registered, 128/240 = 53.3% (two_drugs_one_lab 49/56, clock_time_recheck 0/104, drug_plus_stat_lab 79/80), 0/32 hold orders, 0/108 false orders. Cause: judge bug in clock_time_recheck (rejected an omitted timing, which the tool defines as a single dose). Post-hoc rescore from transcripts (replay validated, 0 mismatches): 224/240 = 93.3%. See docs/CONFIRM3_RESULTS.md and analysis/confirm3_rescore.py.

## Model comparison (2026-10-24)
docs/MODELS_PREREG.md sha256 c8a12748aeed3bb27ffac08c118b6f8e68fa5159cfccb024cfa578d5338a7f28, recorded before any run of Nano, Lightning or Ultra. Runner: analysis/model_compare.py (token counting only).
Deviation 2026-10-24 (before any Ultra run): the Token Factory console shows a balance of $10.64 (usage $41.01 + VAT, almost all Super: 179.8M cached, 66.7M input, 11.4M output tokens). The spend gate in docs/MODELS_PREREG.md for Ultra is lowered from $20 to $5, run as a subsample if needed, and about $3 is reserved for recording the demo. Earlier statements in this repo's notes and chat that the credit had plenty left were not checked against the console.
Deviation 2026-10-24: the comparison is cut for budget. Lightning stopped after 178 of 600 runs (sodium_high complete, phosphate_oral 46, lab_pair_urgent 0): it used about 235k prompt tokens per run and was far below the ADEQUATE bar; its price is not listed. Nano runs on phosphate_oral only (100 runs). Ultra runs a 40-run sample on phosphate_oral to measure its price from the usage page. The ADEQUATE and SAFE criteria are evaluated on what was run and the report says the samples are partial. Balance when decided: $10.30.
Models comparison stopped for budget 2026-10-24 (balance $4.36 after $10.64). Partial results in docs/MODELS_RESULTS.md: Ultra 39/40 on phosphate_oral (Super 55/56), Nano 11 runs weak and token-heavy, Lightning 178 runs far below the bar. Cascade not built (no smaller model safe to screen with). Reserve the remaining balance for recording the demo.
Hosted demo (2026-10-24): docs/demo/index.html built by demo/build_static.py from one real scan on the live model (12 results, 3 acting, 4 orders, none on the held patient; taken as is, no selection). Verified in a browser; read-only; FHIR counts unchanged (21991/0/563426). Cost: a few cents.
