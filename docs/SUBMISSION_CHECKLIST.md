# Submission checklist (as of 2026-10-24)

Deadline: 30 Oct 2026, 10:00 PDT. Requirements re-read from the official rules page (nebiusglobalaihackathon.devpost.com/rules) on 2026-10-24.

| requirement | status | what closes it |
|---|---|---|
| Runs on Nebius Token Factory or Nebius AI Cloud | **done**: the pilot, the watch run and the held-out run all used Token Factory | nothing |
| Uses at least one NVIDIA open model | **done**: `nvidia/nemotron-3-super-120b-a12b`, id confirmed on the account | nothing |
| Public repo with an OSS license | LICENSE (Apache-2.0) in place; committed locally, not published | create the GitHub repo and push when you decide to |
| Demo video under 3 minutes | script ready (`docs/DEMO_SCRIPT.md`), results numbers filled | record it against the live model (`medgate serve --ward demo/ward.json --model ... --base-url ...`), not the replay |
| Devpost write-up | draft ready (`docs/SUBMISSION_DRAFT.md`) | fill the repo URL and the video URL; re-read it against the final numbers |
| "What changed" note for pre-existing projects | likely not needed | project started 2026-10-12; confirm on the rules page |
| Track fits (Stage One is pass/fail on this) | **changed**: Best Apps and Agents. The rules define Coding and Agentic Engineering as agents that write, run and test code | draft now says Best Apps and Agents |
| Feedback on Token Factory, AI Cloud and NVIDIA tools (required form field; also enters the Most Valuable Feedback prize) | written in the draft from what we observed | re-read before pasting |
| URL to a working demo, hosted app or test build (required for every track but Physical AI) | **built, not yet public**: `docs/demo/index.html`, a read-only recorded scan from the live model, verified in a browser (scan renders, Approve writes nothing, no paths or keys in the files) | after the repo is public, enable GitHub Pages on `/docs`; the URL is `https://<account>.github.io/<repo>/demo/` |
| README highlights how Nemotron and Token Factory are used | done: section "Where Nemotron and Nebius are used" | nothing |
| Video: public YouTube, under 3 minutes, footage of the project running, no third-party trademarks or copyrighted music | script ready | record, then check the video has no music or logos |
| Existing project note | not needed: started 2026-10-12, inside the window that opened 2026-08-26 | nothing |
| No financial or preferential support from the Sponsor | the hackathon's own Builder Program credits are open to all entrants; no contract or funding | nothing |
| Eligibility | individual, age of majority; India is not an excluded location | nothing |
| Grader not redistributed | done | `vendor/` is gitignored; README points to the authors' link |

## Results to cite (all pre-registered, Nemotron 3 Super on Nebius)

- Pilot: docs/PILOT_RESULTS.md (13/30 reference loop, 27/30 tool agent).
- Watch on the demo ward: docs/WATCH_RESULTS.md (23 of 27 graded runs correct, silent misses the main failure).
- Held-out test of the fix: docs/HELDOUT_RESULTS.md (silent misses 33 of 120 runs to 0, no false orders).
- Protocol bank and three fresh-protocol confirmations: docs/BANK_RESULTS.md, docs/CONFIRM_RESULTS.md (88.3%, caution), docs/CONFIRM2_RESULTS.md (92.5%, supported), docs/CONFIRM3_RESULTS.md (53.3% fail as registered on a judge bug, 93.3% after a labelled post-hoc fix).
- What the gates catch, without a model: docs/GATE_CATCH.md.

## Order of work before the deadline

1. Start the FHIR server (`work/fhir-server/run_fhir.sh`) and run `uv run pytest`.
2. Record the demo on the live model; delete the order written during recording so the server returns to its baseline counts.
3. Fill the two URLs in the Devpost draft; remove every `[BRACKETED]` placeholder.
4. Create the public repo, push, submit. Pushing and submitting need your go-ahead.

## Time risk

The model runs are done. What is left is recording and form-filling. Keep the demo on an event the live model handles reliably, and say what it does and does not show.
