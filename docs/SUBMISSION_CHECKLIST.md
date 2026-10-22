# Submission checklist (as of 2026-10-22)

Deadline: 30 Oct 2026, 10:00 PDT. Requirements are from notes taken from the hackathon page on 2026-10-06; re-read the official rules page before submitting.

| requirement | status | what closes it |
|---|---|---|
| Runs on Nebius Token Factory or Nebius AI Cloud | **done**: the pilot, the watch run and the held-out run all used Token Factory | nothing |
| Uses at least one NVIDIA open model | **done**: `nvidia/nemotron-3-super-120b-a12b`, id confirmed on the account | nothing |
| Public repo with an OSS license | LICENSE (Apache-2.0) in place; committed locally, not published | create the GitHub repo and push when you decide to |
| Demo video under 3 minutes | script ready (`docs/DEMO_SCRIPT.md`), results numbers filled | record it against the live model (`medgate serve --ward demo/ward.json --model ... --base-url ...`), not the replay |
| Devpost write-up | draft ready (`docs/SUBMISSION_DRAFT.md`) | fill the repo URL and the video URL; re-read it against the final numbers |
| "What changed" note for pre-existing projects | likely not needed | project started 2026-10-12; confirm on the rules page |
| Grader not redistributed | done | `vendor/` is gitignored; README points to the authors' link |

## Results to cite (all pre-registered, Nemotron 3 Super on Nebius)

- Pilot: docs/PILOT_RESULTS.md (13/30 reference loop, 27/30 tool agent).
- Watch on the demo ward: docs/WATCH_RESULTS.md (23 of 27 graded runs correct, silent misses the main failure).
- Held-out test of the fix: docs/HELDOUT_RESULTS.md (silent misses 33 of 120 runs to 0, no false orders).
- What the gates catch, without a model: docs/GATE_CATCH.md.

## Order of work before the deadline

1. Start the FHIR server (`work/fhir-server/run_fhir.sh`) and run `uv run pytest`.
2. Record the demo on the live model; delete the order written during recording so the server returns to its baseline counts.
3. Fill the two URLs in the Devpost draft; remove every `[BRACKETED]` placeholder.
4. Create the public repo, push, submit. Pushing and submitting need your go-ahead.

## Time risk

The model runs are done. What is left is recording and form-filling. Keep the demo on an event the live model handles reliably, and say what it does and does not show.
