# Demo script (target 2:40, limit 3:00)

Screen recording of the review screen, from a live run against Nemotron on Nebius, not the replay. Every `[BRACKETED]` item comes from the real run. If the replay is shown instead, the page labels it as scripted and the voice-over must say so.

Start the screen before recording:

```bash
uv run medgate serve --ward demo/ward.json --model [MODEL] --base-url [URL] --key-file [KEY_FILE]
```

## 0:00 to 0:20, the pain

On screen: docs/PAIN.md table, the three checked rows.

Say: "A potassium result comes back low. Someone has to notice it, read the unit's protocol, work out the dose, write the order and remember the recheck. Studies find between 7 and 62 percent of lab tests never followed up. Even with a nurse protocol, one ward took 112 minutes from result to dose. Protocols help. They still wait for a person to notice."

## 0:20 to 0:45, the ward and the protocols

On screen: the Results watch view, the ward list and the two protocol texts, opened.

Say: "This is a ward of seven synthetic patients and two protocols in plain text, potassium and magnesium. The watch takes each patient's newest covered result from the last 24 hours. No code decides what is abnormal. Nemotron reads the protocol and decides."

## 0:45 to 1:25, the worklist

On screen: click Check new results. Wait for the summary line. Open the potassium card for S6550627.

Say: "[N] new results checked. [K] need action, [ORDERS] orders drafted. This potassium of 3.1 is below the protocol line, so it drafted an oral replacement, 40 milliequivalents, and the paired recheck, stat, next morning at 8. Each order says what it is based on, the lab result itself, and the gates checked that the record it cites was really retrieved."

## 1:25 to 1:50, the hold

On screen: scroll to S0722219 magnesium. Show the agent note.

Say: "This magnesium is low too, 1.7. The agent did not order. It looked up the kidney function, an eGFR of 41, found the protocol's exclusion and held it for a pharmacist. It checked something in the record, not just the number it was given."

(Use the real run's wording. If the live agent orders here, show that honestly and say it missed the exclusion.)

## 1:50 to 2:10, one tap, then the chart

On screen: click Approve and write on a magnesium order. Show the written order with its route and dose.

Say: "Nothing was in the chart until this click. Now it is written as standard FHIR, read back from the server and compared field by field. Here it is: IV, 1 gram over 1 hour, with the citation intact."

Delete the written order afterwards, off camera, so the server returns to its baseline counts.

## 2:10 to 2:35, the numbers

On screen: the output of `medgate pilot runs/pilot_A.jsonl runs/pilot_T.jsonl`.

Say: "We fixed this pilot before any output: 30 benchmark tasks, graded by Stanford's own grader. The same model, Nemotron on Nebius, got 13 of 30 on the benchmark's reference loop and 27 of 30 with our tool-calling agent. Our rule said that at 27 or more there is little room for the checks to raise success, so we dropped that claim. The harness is what mattered. Then we found the agent sometimes finished without ordering. A one-time self-review before it finishes took that from 33 of 120 runs to zero on events it had never seen, with no false orders. It costs about one more model call per result."

## 2:35 to 2:55, the honest limits

Say: "Synthetic patients, no clinician has used this, and 30 tasks is a pilot. The claim that a ready-written order beats an order set with an alert is a hypothesis nobody has tested. The kidney threshold in the demo is invented."

## Recording checklist

- No API key, key file contents or session links on screen.
- Terminal and browser text large enough to read at 720p.
- Counts back to baseline after recording (MedicationRequest 21991, ServiceRequest 0, Observation 563426).
- Upload as unlisted or public on YouTube; paste the link in the Devpost form.
