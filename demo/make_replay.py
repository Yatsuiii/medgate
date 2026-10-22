"""Build the review screen's demo files from the live FHIR server.

demo/ward.json: a ward of MedAgentBench patients and two unit protocols in plain text, potassium and magnesium
replacement, written from the benchmark's own task 9 and task 5 wording, plus one invented exclusion for magnesium
(hold when eGFR is below 45; a demo value, not clinical guidance). The ward mixes low and normal results and one
held patient.

demo/replay.json: scripted, correct agent runs for the ask view (the task 9 patient with low potassium) and for every
result the watch finds on that ward. Each run applies the protocol to the triggering value the way the protocol text
says. The replay lets the screen be seen without a model; the page labels it as scripted.

Usage, from the repository root with the FHIR server up:
    uv run python -I demo/make_replay.py demo
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from medgate.fhir import FhirClient
from medgate.protocol import FHIR_BASE
from medgate.tasks import load_tasks
from medgate.watch import Event, Protocol, Ward, case_for, new_results

NOW = "2023-11-13T10:15:00+00:00"
WINDOW_HOURS = 24.0
POTASSIUM = Protocol(
    "Potassium replacement",
    "K",
    "Potassium replacement protocol (serum potassium, code K). If the newest potassium is below 3.5 mmol/L, order "
    "oral potassium replacement, NDC 40032-917-01, 10 mEq for every 0.1 mmol/L below 3.5, route oral, and pair that "
    "order with a serum potassium level, LOINC 2823-3, priority stat, to be drawn the next morning at 08:00. If the "
    "potassium is 3.5 or higher, order nothing.",
)
MAGNESIUM = Protocol(
    "Magnesium replacement",
    "MG",
    "Magnesium replacement protocol (serum magnesium, code MG, drawn in the last 24 hours). By the newest level, "
    "order IV magnesium, NDC 0338-1715-40, route IV: 1.5 to 1.9 mg/dL, 1 g over 1 hour; 1.0 to below 1.5 mg/dL, 2 g "
    "over 2 hours; below 1.0 mg/dL, 4 g over 4 hours. Record the dose in g and the duration as a rate in hours. If "
    "the level is above 1.9 mg/dL, order nothing. Exclusion: before ordering, check the newest eGFR (code EGFR). If it "
    "is below 45 mL/min/1.73m2, do not order magnesium; hold it for pharmacist review.",
)


def newest(fhir: FhirClient, mrn: str, code: str) -> dict[str, Any] | None:
    url = f"{FHIR_BASE}Observation?patient={mrn}&code={code}&_count=5000&_format=json"
    found = [e["resource"] for e in json.loads(str(fhir.get(url).data)).get("entry", [])]
    found = [r for r in found if datetime.fromisoformat(r["effectiveDateTime"]) <= datetime.fromisoformat(NOW)]
    return max(found, key=lambda r: datetime.fromisoformat(r["effectiveDateTime"]), default=None)


def recent(reading: dict[str, Any] | None) -> bool:
    now = datetime.fromisoformat(NOW)
    return reading is not None and datetime.fromisoformat(reading["effectiveDateTime"]) >= now - timedelta(hours=24)


HELD_PATIENT = "S0722219"  # a task 9 patient (no task 5 case): Mg 1.7 and eGFR 41, so the exclusion holds the order


def pick_ward(fhir: FhirClient) -> list[str]:
    """Benchmark patients with a recent result: one low potassium, two normal, two low magnesium, one normal, and the
    held patient."""
    wanted = [("task9", "K", lambda v: v < 3.5, 1), ("task9", "K", lambda v: v >= 3.5, 2)]
    wanted += [("task5", "MG", lambda v: v <= 1.9, 2), ("task5", "MG", lambda v: v > 1.9, 1)]
    ward: list[str] = []
    for category, code, test, count in wanted:
        for case in (c for c in load_tasks() if c["id"].startswith(f"{category}_")):
            reading = newest(fhir, case["eval_MRN"], code)
            if count and recent(reading) and test(reading["valueQuantity"]["value"]) and case["eval_MRN"] not in ward:
                ward.append(case["eval_MRN"])
                count -= 1
    return [*ward, HELD_PATIENT]


def turn(name: str, arguments: dict[str, Any], text: str = "") -> dict[str, Any]:
    return {"text": text, "calls": [{"id": f"call_{name}", "name": name, "arguments": json.dumps(arguments)}]}


def order_base(mrn: str, observation_id: str) -> dict[str, Any]:
    return {
        "authoredOn": NOW,
        "status": "active",
        "intent": "order",
        "subject": {"reference": f"Patient/{mrn}"},
        "reasonReference": [{"reference": f"Observation/{observation_id}"}],
    }


def potassium_orders(mrn: str, observation_id: str, value: float) -> list[dict[str, Any]]:
    dose = round((3.5 - value) / 0.1 * 10, 1)
    replacement = {
        **order_base(mrn, observation_id),
        "medicationCodeableConcept": {"coding": [{"system": "http://hl7.org/fhir/sid/ndc", "code": "40032-917-01"}]},
        "dosageInstruction": [{"route": "oral", "doseAndRate": [{"doseQuantity": {"value": dose, "unit": "mEq"}}]}],
    }
    level = {
        **order_base(mrn, observation_id),
        "priority": "stat",
        "code": {"coding": [{"system": "http://loinc.org", "code": "2823-3"}]},
        "occurrenceDateTime": "2023-11-14T08:00:00+00:00",
    }
    return [
        turn("calculator", {"expression": f"(3.5 - {value}) / 0.1 * 10"}),
        turn("medicationrequest_create", replacement),
        turn("servicerequest_create", level),
    ]


def magnesium_orders(mrn: str, observation_id: str, value: float) -> list[dict[str, Any]]:
    grams = 1 if value >= 1.5 else 2 if value >= 1 else 4
    dose = {"doseQuantity": {"value": grams, "unit": "g"}, "rateQuantity": {"value": grams, "unit": "h"}}
    replacement = {
        **order_base(mrn, observation_id),
        "medicationCodeableConcept": {"coding": [{"system": "http://hl7.org/fhir/sid/ndc", "code": "0338-1715-40"}]},
        "dosageInstruction": [{"route": "IV", "doseAndRate": [dose]}],
    }
    return [turn("medicationrequest_create", replacement)]


def scripted_run(event: Event, fhir: FhirClient, reviewed: bool) -> list[dict[str, Any]]:
    """The run a correct agent makes for one event, following the protocol text, exclusion included.

    A watch run ends with a second finish: the first is answered with the finish-time review, as for a real model.
    """
    value = float(event.result["valueQuantity"]["value"])
    low = value < 3.5 if event.protocol.code == "K" else value <= 1.9
    verdict = "below the protocol threshold, so it calls for orders" if low else "within range, so nothing is ordered"
    note = f"Scripted replay: {event.protocol.code} {value} is {verdict}."
    search = turn("observation_search_labs", {"patient": event.patient, "code": event.protocol.code}, note)

    def confirm(reason: str) -> list[dict[str, Any]]:
        """The scripted reply to the review: the same finish, with the reason repeated so the page shows it."""
        return [turn("finish", {"answer": [value]}, reason)] if reviewed else []

    if not low:
        return [search, turn("finish", {"answer": [value]}), *confirm(note)]
    if event.protocol.code == "K":
        orders = potassium_orders(event.patient, str(event.result["id"]), value)
        return [
            search,
            *orders,
            turn("finish", {"answer": [value]}),
            *confirm("Scripted replay: the orders match the protocol."),
        ]
    egfr = newest(fhir, event.patient, "EGFR")
    assert egfr is not None, f"no eGFR for {event.patient}"
    level = float(egfr["valueQuantity"]["value"])
    check = turn("observation_search_labs", {"patient": event.patient, "code": "EGFR"})
    if level < 45:
        hold = f"Scripted replay: eGFR {level} is below 45, so magnesium is held for pharmacist review. No order."
        return [search, check, turn("finish", {"answer": [value]}, hold), *confirm(hold)]
    orders = magnesium_orders(event.patient, str(event.result["id"]), value)
    return [
        search,
        check,
        *orders,
        turn("finish", {"answer": [value]}),
        *confirm("Scripted replay: the order matches the protocol."),
    ]


def main(out: Path) -> None:
    fhir = FhirClient()
    ward = Ward(NOW, WINDOW_HOURS, tuple(pick_ward(fhir)), (POTASSIUM, MAGNESIUM))
    events = new_results(ward, fhir)
    ask_case = next(c for c in load_tasks() if c["id"] == "task9_3")
    ask_event = next(e for e in events if e.patient == ask_case["eval_MRN"] and e.protocol.code == "K")
    ask = {
        "context": ask_case["context"],
        "question": ask_case["instruction"].strip(),
        "turns": scripted_run(ask_event, fhir, reviewed=False),
    }
    watch = {case_for(e, NOW)["id"]: scripted_run(e, fhir, reviewed=True) for e in events}
    protocols = [{"name": p.name, "code": p.code, "text": p.text} for p in ward.protocols]
    ward_file = {"now": NOW, "window_hours": WINDOW_HOURS, "patients": list(ward.patients), "protocols": protocols}
    (out / "ward.json").write_text(json.dumps(ward_file, indent=1) + "\n")
    (out / "replay.json").write_text(json.dumps({"ask": ask, "watch": watch}, indent=1) + "\n")
    print(f"ward {list(ward.patients)}: {len(events)} new results scripted")
    for e in events:
        print(
            f"  {e.patient} {e.protocol.code} {e.result['valueQuantity']['value']} at {e.result['effectiveDateTime']}"
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
