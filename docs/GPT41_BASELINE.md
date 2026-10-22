# What GPT-4.1's published runs teach us (2026-10-14)

The MedAgentBench v2 repository publishes two sets of GPT-4.1 runs on the benchmark's reference loop: temperature 0, at most 8 rounds, the benchmark's own prompt and functions. That loop is what medgate's arm A reproduces.

- `outputs/MedAgentBenchv1-mookass` covers the **original 300 tasks**, the ones medgate uses. It is analysed below.
- `outputs/MedAgentBenchv1` covers v2's 300 new tasks. Its recorded success is 0.643 (193/300 by the published summary). It is not re-graded here, because its grader is in the unlicensed v2 code.

| detail | value |
|---|---|
| Source | github.com/ericoericochen/medagentbenchv2, `medagentbench_v2/src/MedAgentBench/outputs/` (no license; kept outside this repository) |
| runs.jsonl sha256 (original tasks) | b08703c83701f61bac47c39a49e667ef7bab0b966b2bf5b8da24532f44d54374 |
| overall.json sha256 (original tasks) | a1108dccb3ccbfc357f79ad26870b40e289b4ce660fca8f7b1bef04ecda9e844 |
| Record | `index` (= task position), `output.status`, `output.result` (the FINISH text), `output.history` (user/agent messages) |
| Analysis | `uv run python -I analysis/gpt41_baseline.py <run set dir>`; identical output on two runs |

## Result 1: medgate's grader agrees with the published grading on every run

medgate's `grade()` re-graded all 300 runs against the live FHIR server and agrees with the recorded outcome on **300 of 300**. Until now, the grading adapter had only been checked with scripted oracle agents. This is the first check against real model conversations.

## Result 2: GPT-4.1 on the reference loop scores 175/300 (58.3%), and most of its failures are formatting

| category | correct | | category | correct |
|---|---|---|---|---|
| task1 patient lookup | 29/30 | | task6 average glucose, 24 h | 14/30 |
| task2 age | 30/30 | | task7 latest glucose | **0/30** |
| task3 record blood pressure | 30/30 | | task8 referral | 30/30 |
| task4 latest magnesium, 24 h | 23/30 | | task9 potassium check and order | **0/30** |
| task5 magnesium check and order | 16/30 | | task10 A1C check and order | **3/30** |

All 300 runs ended normally: no invalid actions, no round limits.

Why the 125 failures failed. Each failure is counted once, under the first matching reason:

| first reason | runs |
|---|---|
| the answer is a sentence (`["The most recent CBG ... is 191 mg/dL, measured ..."]`) | 73 |
| the answer holds an object or a list (`[{"last_hba1c_value": 5.9, ...}]`, `[[-1]]`) | 23 |
| it read only the first page of results (20, unsorted) | 15 |
| a well-formed answer with the wrong value | 9 |
| no A1C on record and no order placed | 5 |

Counting every reason a failure shows:
- **Partial pages:** 33 failures read only part of the results.
- **Wrong code:** 30 never searched the code the task gives for looking up results. In task 9, GPT-4.1 searched the LOINC ordering code `2823-3` instead of `K`, found nothing, and reported no potassium.

So **96 of the 125 failures (77%) are answer formatting**, not clinical reasoning.

Timestamps were not a problem. All 60 writes in tasks 3 and 8 were graded correct, and that requires the exact time string. No failure had a mistyped timestamp.

## Result 3: the two traps from Phase 6 barely mattered for GPT-4.1

- **Task 9 (normal potassium):** it placed no order on all 29 normal-potassium patients, but only because it never found the potassium values (the wrong code above). Whether it would order the "paired" lab once it sees a normal value is still **UNKNOWN**.
- **Task 10 (no A1C on record):** it ordered on 8 of the 13 patients with no A1C, without any hint. All 8 still failed on answer format. The other 5 placed no order.

## What this means for medgate

1. **Answer format is the biggest lever.** v2's gain from 58% to 91% on GPT-4.1 lines up with what v2 added: a typed finish tool with good and bad examples, newest-first searches, and a search tool that asks for the short lab code, not LOINC.
   - T's finish check nudges numbers written as text or with units. It does not yet catch sentences or objects, and those were 96 of GPT-4.1's 125 failures. That is the next fix.
2. **Partial pages are already fixed in T.** T fetches every match, newest first. The Phase 6 live test shows the newest reading first on all 180 read tasks.
3. **Wrong code is not fixed in T.** When a task names one code for looking up results and another for ordering, T has no guard. A general mitigation: when a search finds nothing, tell the agent to try the other codes and parameters the task gives before concluding the data is missing.
4. **Applied in Phase 8.**
   - The finish check now also catches sentences, objects and nested lists.
   - An empty search now tells the agent to try the task's other codes or parameters.
   - Replayed over GPT-4.1's 300 final answers, the check catches **all 96 format failures**.
   - It would also nudge 76 correct answers, all of them on tasks where the grader ignores the answer: confirmation sentences after the task 3 and task 8 writes (60), and "no magnesium recorded" sentences in task 5 (16). Each nudge costs one round and can never cost the answer. T's prompt asks for `[]` on action-only tasks, so in T this count should be lower.
5. **For the pilot:** the reference loop (arm A) on a strong 2025 model fails mostly on format. Arm A on Nemotron will probably look the same, so the A versus T gap will mostly measure format and retrieval fixes. That is a harness result, not a clinical one, and should be reported that way.
