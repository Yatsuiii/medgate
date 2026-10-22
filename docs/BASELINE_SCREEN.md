# Baseline and prior-art screen (2026-10-14)

Question: can medgate's current design (gates measured against the v1 reference loop) produce a result that matters, and what is the strongest realistic baseline? This screen should have been run before Phases 1 to 3. It was not.

## What exists

### 1. MedAgentBench v2: the strongest baseline

Chen, Postelnik, Black, Jiang, Chen. *MedAgentBench v2: Improving Medical LLM Agent Design.* Pacific Symposium on Biocomputing 2026, pp. 354-371. [PDF](https://psb.stanford.edu/psb-online/proceedings/psb26/chen_eric.pdf). Read in full (text extracted with pdftotext).

- **What changed from v1:**
  - Structured FHIR tools replace raw HTTP strings (for example `fhir_patient_search` and `fhir_service_request_create`), which "enforced correct formatting".
  - A `finish` tool enforces answer types.
  - A calculator tool handles dose and average arithmetic.
  - A new system prompt asks for a plan, conditional-logic handling and validated preconditions, with few-shot examples of good and bad final answers.
  - Memory is built from failed tasks.
- **Results, all with GPT-4.1:**
  - 91.0% without memory and 98.0% with memory.
  - 96.67% on the tasks that need three or more tool calls (5, 6, 9 and 10), with memory.
  - 88.67% (266/300) on 300 new physician-reviewed tasks.
  - For comparison, the best v1 result is 69.67% (Claude 3.5 Sonnet v2).
- **How memory was built:** from 5 failed tasks per category, with the rest held out, and every memory is given to the agent. My reading: the 30 tasks in a category are one instruction template with different MRNs, so the 98% is close to within-template learning. The 91% has no such issue.
- **Code and license:**
  - The code is at [github.com/ericoericochen/medagentbenchv2](https://github.com/ericoericochen/medagentbenchv2): 10 stars, last push 2025-07-31, **no license**. Its ideas can be reimplemented, but its code and prompt text cannot be copied.
  - The paper itself is CC BY-NC 4.0.

### 2. Symbolic guardrails on MedAgentBench: the safety angle

*Don't Make Models Guess: Symbolic Guardrails for Domain-Specific AI Agents*, [arXiv 2604.15579](https://arxiv.org/html/2604.15579). Code at [github.com/hyn0027/agent-symbolic-guardrails](https://github.com/hyn0027/agent-symbolic-guardrails), Apache-2.0. The numbers below are read from the paper's HTML table.

- The policy has 88 synthetic requirements. Of the 57 in scope, 34 are enforceable and 23 were implemented. API validation alone covers 47% of the enforceable ones.
- Results on MedAgentBench, GPT-5 only:

| condition | unsafe | success rate |
|---|---|---|
| raw (generic GET and POST) | 39.0% | 0.64 |
| baseline (8 tools) | 23.0% | 0.59 |
| guardrail | 0.0% | 0.67 |

- Success rate, guardrail vs raw: p = 0.27. Guardrail vs baseline: p < 0.01 (McNemar).

### 3. Medmarks: open models on the v2 harness

[arXiv 2605.01417](https://arxiv.org/pdf/2605.01417), Appendix N. Code at [github.com/MedARC-AI/Medmarks](https://github.com/MedARC-AI/Medmarks), MIT; its README lists the license of the v2 environment as "not specified".

- They ran a subset of models through a wrapper of the v2 harness on the v1 tasks. GLM 4.7 narrowly beats GPT-5.1 (medium) and clearly beats Claude Sonnet 4.5.
- The scores are only in Figure 12, which is an image and was not read.
- Table 11 classifies the remaining failures where two models disagreed:
  - Where GLM 4.7 succeeded and GPT-5.1 failed: wrong search scope or category 25 (67.6%), winner placed an order and loser abstained 7 (18.9%), missed a required order 2, tool or query formatting 1.
  - Where Qwen3 30B-A3B Thinking succeeded and Qwen3 235B-A22B Thinking failed: **wrong patient reference 51 (72.9%)**, tool or query formatting 10 (14.3%), wrong search scope 9 (12.9%).
- UNKNOWN: whether any Nemotron model is in their MedAgentBench v2 figure. Nemotron Nano V3 30B-A3B and Nemotron Nano 12B V2 are in their open-ended model set.

### 4. Nemotron on MedAgentBench

No published score was found in one standard web search. UNKNOWN, not absent.

## How medgate's arms map onto this

| medgate arm | already covered by |
|---|---|
| A, the v1 reference loop | the weakest baseline on record. v2 gained 21 points with GPT-4.1 from tools and prompting alone |
| B1, format retry | v2's typed `finish` tool and few-shot output examples, which prevent the error instead of retrying after it |
| B2, payload gate | v2's structured create tools (malformed payloads cannot be built) and the guardrail paper's API validation |
| B3, evidence gate | partly open. The guardrail paper enforces patient authorization as policy. Medmarks shows wrong-patient-reference failures in one model pair. medgate's gate currently checks writes only |

## Verdict: PIVOT (for the current framing)

- **A win means little.** If B3 beats A by 5 points or more, that only shows medgate beats a harness that is already known to be weak. A reviewer will answer with v2's +21.
- **A loss is a null against the same weak baseline.** It is informative, but not a submission.
- **The safety framing is taken.** Its main result is already published with Apache-2.0 code: 0% unsafe actions by construction, and no significant loss of success against raw.
- **What is open, as far as found:**
  - (a) a Nemotron score on a v2-class harness;
  - (b) whether mechanical gates add anything on top of a v2-class harness for an open model, especially an evidence gate on every call, aimed at wrong-patient references.

## Proposed redesign (a proposal awaiting the user's decision, not started)

- **New arm A'.** A v2-class agent written from the paper's description, not from the v2 code:
  - native tool calling with structured FHIR tools;
  - a typed `finish` tool and a calculator;
  - our own planning prompt.
  - Tool calls are translated into the v1 history format, so the vendored grader still scores them.
  - It is validated with scripted agents and the real grader, as in Phase 2.
- **New arm G.** A' plus medgate's gates, with the evidence gate extended from writes to every call.
- **Headline either way:** the Nemotron score on A', next to GPT-4.1's published 91.0%. This has to be labelled a different harness implementation, not a matched comparison.
- **Proposed pilot before the full run.** 30 tasks, 3 per category, A' only. Thresholds are a draft, to be frozen before any model output:
  - 27 or more of 30: little room for gates. Make the story open-model parity and drop gate claims.
  - 18 to 26: classify the failures. Build gates only for classes that could be worth 5 points or more on the full run.
  - 17 or fewer: check the harness for bugs first, then consider a larger Nemotron model.
- **Pilot access without Nebius:**
  - OpenRouter lists free `nvidia/nemotron-3-super-120b-a12b:free` and `nvidia/nemotron-3-nano-30b-a3b:free` endpoints. Their rate limits and terms are UNVERIFIED. The free endpoints log prompts, which is acceptable only because MedAgentBench data is synthetic.
  - The final submission must still run on Nebius under the hackathon rules.
