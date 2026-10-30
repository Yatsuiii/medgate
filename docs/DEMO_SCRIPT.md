# Demo script (target 2:40, limit 3:00)

Screen recording of the review screen, from a live run against Nemotron on Nebius, not the replay. The numbers below are from the rehearsal; re-check them on the take. If the replay is shown instead, the page labels it as scripted and the voice-over must say so.

Start the screen before recording:

```bash
uv run medgate serve --ward demo/ward.json --model nvidia/nemotron-3-super-120b-a12b \
  --base-url https://api.tokenfactory.nebius.com/v1/ --key-file ~/.nebius_key --max-tokens 8192
```

Open http://127.0.0.1:8765. Dress rehearsal 2026-10-22 on the live model, four scans in a row, identical each time: about 18 seconds, 12 results checked, 3 results needing action, 4 orders (potassium 3.1: 2, magnesium 1.8: 1, magnesium 1.9: 1), 0 orders on the other 9 including the held one. Nothing was approved, so the server stayed at its baseline counts. A scan is stochastic, so check the worklist matches the lines below before talking over it.

## 0:00 to 0:20, the pain

On screen: docs/PAIN.md table, the three checked rows.

Say: "A potassium result comes back low. Someone has to notice it, read the unit's protocol, work out the dose, write the order and remember the recheck. Studies find between 7 and 62 percent of lab tests never followed up. Even with a nurse protocol, one ward took 112 minutes from result to dose. Protocols help. They still wait for a person to notice."

## 0:20 to 0:45, the ward and the protocols

On screen: the Results watch view, the ward list and the two protocol texts, opened.

Say: "This is a ward of seven synthetic patients and two protocols in plain text, potassium and magnesium. The watch takes each patient's newest covered result from the last 24 hours. No code decides what is abnormal. Nemotron reads the protocol and decides."

## 0:45 to 1:25, the worklist

On screen: click Check new results. Wait for the summary line. Open the potassium card for S6550627.

Say: "Twelve new results checked. Three need action, four orders drafted. This potassium of 3.1 is below the protocol line, so it drafted an oral replacement, 40 milliequivalents, and the paired recheck, stat, next morning at 8. Each order says what it is based on, the lab result itself, and the gates checked that the record it cites was really retrieved."

## 1:25 to 1:50, the hold

On screen: scroll to S0722219 magnesium. The card says no order drafted; open its steps and show the eGFR lookup. The page does not show the agent's reason (it prints "The agent's reason is not checked"), so do not read one out.

Say: "This magnesium is low too, 1.7, and the agent drafted nothing. In its steps it looked up the kidney function first. The protocol excludes patients with an eGFR under 45, and this patient's is 41. It checked the record, not only the number it was given. The page shows no order and does not check the agent's reason, which is why a person still reads this row."

(If the live agent orders here, show that honestly and say it missed the exclusion. The rehearsal drafted nothing on all four scans.)

## 1:50 to 2:10, one tap, then the chart

On screen: click Approve and write on the S6542579 magnesium order (rate unit h, the form the check expects; the S3084624 one writes g/h). Show the written order with its route and dose.

Say: "Nothing was in the chart until this click. Now it is written as standard FHIR, read back from the server and compared field by field. Here it is: IV, 1 gram over 1 hour, with the citation intact."

Delete the written order afterwards, off camera, so the server returns to its baseline counts.

## 2:10 to 2:40, the numbers

On screen: the Results section of the README, then the Nebius and NVIDIA section.

Say: "We wrote down our tests before running them. On three protocols the agent had never seen, written only as plain text, Nemotron Super on Nebius got 407 of 440 orders right, 92.5 percent, with no unsafe order. The next set failed our own rule, 53 percent, because our grader rejected a correct default. We reported that, fixed the grader, and rescored from saved transcripts: 93 percent, labelled after the fact. A second Nemotron checking the drafts caught 31 of 33 wrong order sets and raised no false alarm on 80 correct ones. That is detection only. We did not test whether the drafter fixes them."

## 2:40 to 2:58, the honest limits

Say: "Synthetic patients, one model, no clinician has used this. Protocols and graders were written by a model. Whether a ready-written order beats an order set with an alert is untested. The kidney threshold in the demo is invented."

## Recording checklist

- No API key, key file contents or session links on screen.
- Terminal and browser text large enough to read at 720p.
- Counts back to baseline after recording (MedicationRequest 21991, ServiceRequest 0, Observation 563426).
- Upload as unlisted or public on YouTube; paste the link in the Devpost form.
