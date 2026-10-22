# The pain medgate's results watch is for

A lab result comes back abnormal. Someone has to notice it, work out what the unit's protocol says, write the order and remember the recheck. Each of those steps is where results get missed or acted on late.

## What the literature says

Evidence is literature only, by the user's choice (2026-10-14). No clinician has been asked.

| finding | source | checked on |
|---|---|---|
| In 19 studies of outpatients, 6.8% to 62% of laboratory tests were never followed up (radiology: 1.0% to 35.7%). Reported harms include hospital visits for hyperkalaemia after missed abnormal potassium results. | Callen, Westbrook, Georgiou, Li. *Failure to follow-up test results for ambulatory patients: a systematic review.* J Gen Intern Med 2012;27(10):1334-48. [PMC3445672](https://pmc.ncbi.nlm.nih.gov/articles/PMC3445672) | primary page |
| Primary care physicians received 76.9 inbox notifications a day, 20.2% of them test results. The time is an estimate of about 67 minutes a day, extrapolated from earlier VA work and not measured. Sample: 92 physicians, 3 Texas practices, January to June 2015. | Murphy et al. *The burden of inbox notifications in commercial electronic health records.* JAMA Intern Med 2016;176(4):559-60. [PMC4860883](https://pmc.ncbi.nlm.nih.gov/articles/PMC4860883) | primary page |
| On a haematologic malignancy ward, a nurse-driven electrolyte replacement protocol cut the average time from lab result to medication from 344 to 112 minutes, with fewer reported arrhythmias. | Gopalsami, Wheatley. Clin J Oncol Nurs 2023;27(1):81-85. [ONS](https://www.ons.org/cjon/27/1/implementation-and-evaluation-inpatient-electrolyte-replacement-protocol-patients) | abstract page (full text behind a login) |
| Among hospitalised patients, 20% to 61.6% of test results lacked follow-up. | Callen et al., BMJ Qual Saf 2011 (review of 12 studies) | search summary only, not checked |
| A pharmacist-driven protocol on general medicine wards shortened potassium replacement from 4.9 to 2.9 hours and magnesium from 5.0 to 3.9 hours, and missed follow-up lab orders fell from 12.7% to 1.4%. | residency conference abstract (single centre, retrospective) | search summary only, not checked |

The protocol studies show two things. Protocols help a great deal, and they still depend on a person noticing the result and building the order. That second dependency is the gap the results watch aims at.

## What the results watch does about it

- **Notices.** For every patient on a ward and every unit protocol, it takes the newest result the protocol covers that arrived inside the time window (src/medgate/watch.py). Whether that result is abnormal is not decided here.
- **Applies the protocol and drafts.** The gated agent reads the protocol's own text and either drafts the orders it calls for or orders nothing. Each order is cited to the triggering result in FHIR's reasonReference, and its fields, types and citations are checked by the gates.
- **Waits for a person.** Nothing is written until a clinician approves the order on the review screen. An approved order is converted to conformant FHIR and read back field by field.

## What is not shown

- **Untested advantage.** Over a protocol order set with an alert, the claimed advantage is that the order is already written, with the dose computed, the recheck paired and the lab shown, so acting takes one tap. No study or user has tested this. It is a hypothesis.
- **The watch has not run on a model.** Scripted watch runs on benchmark patients grade correct (tasks 5 and 9), which shows the plumbing is correct, not that a model applies protocols reliably. The pilot (docs/PILOT_RESULTS.md) measured the benchmark's tasks with the same model, not the watch.
- **Hand-written protocols.** The demo's protocol texts are written from the benchmark's own task wording. Real protocols are longer. The demo's magnesium protocol has one invented exclusion (hold when eGFR is below 45) so the agent must check the record; the threshold is a demo value, not clinical guidance, and the potassium protocol has no exclusions.
- **Synthetic data, no clinical claims.** The records are MedAgentBench's synthetic patients.
