# Pilot protocol: Nemotron on arms A and T

**Status: FROZEN 2026-10-15.** The user approved the Phase 12 plan, which named the recommended choices below (sampling b, thresholds as written). The sha256 of this file is in NOTES.md and is recorded before the first model call. From here nothing changes; any later change is a dated deviation note.

## Question

How does an NVIDIA open model do on MedAgentBench with a v2-class tool-calling harness (arm T), compared with the benchmark's reference loop (arm A) on the same tasks? And where does T fail?

This answers the open question from docs/BASELINE_SCREEN.md: is there room for gates on top of a strong harness, or is open-model parity the story?

## Fixed design

- **Endpoint:** the NVIDIA API at `https://integrate.api.nvidia.com/v1` (OpenAI-compatible).
  - This is for development only. The hackathon submission must still run on Nebius.
  - The key is read from a file the user creates (`~/.nvidia_key`). It is never printed or logged.
- **Model:** `nvidia/nemotron-3-super-120b-a12b`. The id comes from NVIDIA's API reference page title and is UNVERIFIED against the user's catalog. If the endpoint rejects it, the corrected id is a dated deviation, not a new design.
- **Tasks:** 30 in all, 3 per category, chosen with one `r = random.Random(0)`, calling `sorted(r.sample(range(1, 31), 3))` for categories 1 to 10 in order (the list below was reproduced from this and matches):
  `task1_13,task1_25,task1_28,task2_2,task2_14,task2_29,task3_9,task3_16,task3_17,task4_13,task4_26,task4_30,task5_10,task5_16,task5_27,task6_12,task6_19,task6_29,task7_7,task7_17,task7_30,task8_5,task8_10,task8_25,task9_4,task9_20,task9_26,task10_9,task10_18,task10_30`
- **Arms:**
  - A is the reference loop, unchanged.
  - T is the tool agent: structured FHIR tools from funcs_v1.json; searches that fetch every match and show it compact and newest first, with `_sort` and `_count` for the agent; a calculator; a finish tool with a one-time type check; and our own planning prompt. The design is in src/medgate/tool_agent.py, src/medgate/tools.py and src/medgate/results.py and is frozen as of this file's hash.
  - TG is not part of the pilot. The pilot measures the baseline and its failures; gates come after.
- **Runs:** one run per task per arm, pass@1, graded by the benchmark's own grader. At most 8 model calls per task.
- **Commands:** the server is `work/fhir-server/run_fhir.sh`.

```bash
TASKS=task1_13,task1_25,...   # the 30 ids above
for arm in A T; do
  uv run medgate run --arm $arm --model nvidia/nemotron-3-super-120b-a12b \
    --base-url https://integrate.api.nvidia.com/v1 --key-file ~/.nvidia_key \
    --tasks $TASKS --out runs/pilot_$arm.jsonl --pause 2 \
    --temperature 1.0 --top-p 0.95 --max-tokens 8192
done
uv run medgate compare runs/pilot_A.jsonl runs/pilot_T.jsonl
```

- **Errors:** a rate limit (429), a server error (5xx) or a dropped connection is retried up to 5 attempts, waiting for Retry-After or 2, 4, 8 seconds (at most 60). Any other error, or the fifth failure, stops the run with a clear message. Rerunning the same command resumes, and an interrupted task restarts from scratch. Every restart is noted in the results.
- **Reply handling:** text before a closing think tag is dropped from the model's reply; null content counts as an empty reply; a reply with no tool call gets the reminder; tool arguments that are not valid JSON are returned to the model as an error. `--max-tokens 8192` is set so a reasoning model is not cut off by a provider default.
- **Spend:** none. The NVIDIA API's free terms are UNVERIFIED; if it asks for payment, stop and ask.

## Choices (closed at the freeze)

1. **Sampling: (b) is chosen.**
   - (a) Temperature 0, the Phase 1 design.
   - (b) Temperature 1.0 and top_p 0.95, which NVIDIA reportedly recommends for this model, including for tool calling. That comes from secondary sources and is UNVERIFIED on the model card.
   - Recommendation: (b). A reasoning model under greedy decoding is a known weak setting, and the baseline should be the model as its makers recommend running it.
   - Flags: `--temperature 1.0 --top-p 0.95`.
2. **Decision thresholds, as written, on T's correct count out of 30:**
   - 27 or more: there is little room for gates. The story is open-model parity, and gate claims are dropped.
   - 18 to 26: classify the failures (below). Build gates only for classes that could be worth 5 points or more on the full 300.
   - 17 or fewer: read 5 failing transcripts for harness bugs first, then consider a larger Nemotron model.

## Failure classes (fixed before any output)

Every failure of T gets exactly one primary class, assigned by reading its transcript:

1. **Wrong patient:** a search or write for a patient other than the task's.
2. **Retrieval:** no sort, filter or count where one was needed, so the data was wrong or incomplete (for example, not the newest value).
3. **Arithmetic:** a wrong calculation (dose, average, age, time window).
4. **Condition:** acted when the condition did not hold, or did not act when it did. This includes the scope of "pair this order with".
5. **Payload:** a write with a wrong or missing code, system, value, unit, time, route or field.
6. **Answer format:** right content, wrong shape or type in finish (a string for a number, units, date format, number of values).
7. **Never finished:** hit the round limit, or no finish.
8. **Other:** described in words.

TG's gates can catch class 1 and the missing-field and wrong-type part of class 5 mechanically. Classes 2, 3, 4 and 6 are not addressable by the gates as designed.

## What gets reported

- Correct counts for A and T on the 30 tasks, per category, with the paired discordant counts.
- With 30 tasks, a 95% interval is roughly plus or minus 17 points, so this is a pilot and nothing more.
- T's failures by class, with task ids and transcript excerpts.
- The threshold decision, applied as written.

## What will not be concluded

- Nothing about parity with GPT-4.1's published 91.0%: the harness implementation is different and there are only 30 tasks.
- Nothing clinical.
