"""Anemia iron protocol: two lab ServiceRequests plus tiered oral ferrous sulfate, with an eGFR exclusion.

Trigger lab is hemoglobin (HGB). Oracle (needs), judge (accurate) and hand-coded rule script (rule_payloads).
The ferrous sulfate NDC is not in the MedAgentBench data (no iron product there); it is stated in the text, like
the other protocols' NDCs, and the judge matches the text. Analysis code only.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from heldout import newest  # noqa: E402
from heldout_run import _close, _code, _dict, _first, _route  # noqa: E402

NDC = "0904-1034-60"  # ferrous sulfate 325 mg tablet; not present in the benchmark data
IRON_PANEL, FERRITIN = "24448-6", "2276-4"
TRIGGER, SPLIT, EGFR_FLOOR, LAB_HOURS = 8.0, 7.5, 30.0, 4

PROTOCOL = {
    "name": "Anemia iron workup",
    "code": "HGB",
    "text": (
        "Anemia iron protocol (hemoglobin, code HGB, drawn in the last 24 hours). If the newest hemoglobin is below "
        "8.0 g/dL, order three things. First, an iron panel (iron and iron binding capacity), LOINC 24448-6, a "
        "ServiceRequest, priority routine, to be collected 4 hours after the order is written. Second, a serum "
        "ferritin, LOINC 2276-4, a ServiceRequest, priority routine, to be collected 4 hours after the order is "
        "written. Third, oral ferrous sulfate, a MedicationRequest, NDC 0904-1034-60, route oral, once daily, by "
        "level: 7.5 to below 8.0 g/dL, 325 mg per dose for 14 days; below 7.5 g/dL, 650 mg per dose for 30 days. "
        "Record the dose in mg. If the hemoglobin is 8.0 g/dL or higher, order nothing. Exclusion: before ordering, "
        "check the newest eGFR (code EGFR). If it is below 30 mL/min/1.73m2, do not order anything; hold it for "
        "physician review of anemia of chronic kidney disease."
    ),
}


def needs(fhir: Any, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    hgb = newest(fhir, mrn, "HGB", now)
    if hgb is None or hgb[1] < now - window:
        return None
    if hgb[0] >= TRIGGER:
        return {"orders": 0, "held": False, "value": hgb[0]}
    egfr = newest(fhir, mrn, "EGFR", now)
    if egfr is None:  # the exclusion cannot be applied
        return None
    if egfr[0] < EGFR_FLOOR:
        return {"orders": 0, "held": True, "value": hgb[0], "egfr": egfr[0]}
    mg, days = (650, 30) if hgb[0] < SPLIT else (325, 14)
    return {"orders": 3, "held": False, "value": hgb[0], "mg": mg, "days": days, "egfr": egfr[0]}


def _instant(x: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except ValueError:
        return None
    if "T" not in str(x):
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _mg(dose: dict[str, Any]) -> float | None:
    q = _dict(dose.get("doseQuantity"))
    v, unit = q.get("value"), str(q.get("unit") or q.get("code") or "").strip().lower()
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    scale = {"mg": 1.0, "milligram": 1.0, "milligrams": 1.0, "g": 1000.0, "gram": 1000.0, "grams": 1000.0}.get(unit)
    return None if scale is None else v * scale


def _days(q: Any) -> float | None:
    q = _dict(q)
    v, unit = q.get("value"), str(q.get("unit") or q.get("code") or "").strip().lower()
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    scale = {"d": 1.0, "day": 1.0, "days": 1.0, "h": 1 / 24, "hr": 1 / 24, "hour": 1 / 24, "hours": 1 / 24}.get(unit)
    return None if scale is None else v * scale


def _snomed_oral(p: dict[str, Any]) -> bool:
    return _code(_first(p.get("dosageInstruction")), "route") == "26643006"


def _once_daily_for(p: dict[str, Any], days: int) -> bool:
    instr = _first(p.get("dosageInstruction"))
    rep = _dict(_dict(instr.get("timing")).get("repeat"))
    freq, per, pu = rep.get("frequency"), rep.get("period"), str(rep.get("periodUnit", "")).lower()
    daily = (freq, per) == (1, 1) and pu in ("d", "day", "days") or (freq, per, pu) == (1, 24, "h")
    if not daily:
        return False
    lengths = [
        _days(rep.get("boundsDuration")),
        _days(_dict(p.get("dispenseRequest")).get("expectedSupplyDuration")),
        float(rep["count"])
        if isinstance(rep.get("count"), int | float) and not isinstance(rep.get("count"), bool)
        else None,
    ]
    return any(x is not None and _close(x, days) for x in lengths)


def _iron_ok(p: dict[str, Any], mg: float, days: int) -> bool:
    dose = _first(_first(p.get("dosageInstruction")).get("doseAndRate"))
    amount = _mg(dose)
    return (
        p.get("resourceType", "MedicationRequest") == "MedicationRequest"
        and _code(p, "medicationCodeableConcept") == NDC
        and (_route(p) in ("oral", "po") or _snomed_oral(p))
        and amount is not None
        and _close(amount, mg)
        and _once_daily_for(p, days)
    )


def _lab_ok(p: dict[str, Any], loinc: str, due: datetime) -> bool:
    t = _instant(p.get("occurrenceDateTime"))
    return (
        p.get("resourceType", "ServiceRequest") == "ServiceRequest"
        and _code(p, "code") == loinc
        and str(p.get("priority", "")).lower() == "routine"
        and t is not None
        and abs((t - due).total_seconds()) < 60
    )


def accurate(need: dict[str, Any], payloads: list[dict[str, Any]], now: datetime) -> bool:
    try:
        if not isinstance(payloads, list):
            return False
        if int(need["orders"]) == 0:
            return not payloads
        if len(payloads) != 3 or not all(isinstance(p, dict) for p in payloads):
            return False
        now = now if now.tzinfo else now.replace(tzinfo=UTC)
        due = now + timedelta(hours=LAB_HOURS)
        iron = [p for p in payloads if _iron_ok(p, float(need["mg"]), int(need["days"]))]
        panel = [p for p in payloads if _lab_ok(p, IRON_PANEL, due)]
        ferr = [p for p in payloads if _lab_ok(p, FERRITIN, due)]
        return len(iron) == 1 and len(panel) == 1 and len(ferr) == 1  # one of each, three distinct orders
    except Exception:  # noqa: BLE001 - a malformed payload is a wrong answer, never a crash
        return False


def rule_payloads(fhir: Any, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    hgb, egfr = newest(fhir, mrn, "HGB", now), newest(fhir, mrn, "EGFR", now)
    if hgb is None or hgb[1] < now - window or hgb[0] >= TRIGGER or egfr is None or egfr[0] < EGFR_FLOOR:
        return []
    mg, days = (650, 30) if hgb[0] < SPLIT else (325, 14)
    due = (now + timedelta(hours=LAB_HOURS)).isoformat(timespec="seconds")
    subject = {"reference": mrn}
    repeat = {"frequency": 1, "period": 1, "periodUnit": "d", "boundsDuration": {"value": days, "unit": "d"}}
    lab = lambda loinc: {  # noqa: E731
        "code": {"coding": [{"code": loinc}]},
        "priority": "routine",
        "occurrenceDateTime": due,
        "subject": subject,
    }
    return [
        {
            "medicationCodeableConcept": {"coding": [{"code": NDC}]},
            "dosageInstruction": [
                {
                    "route": "oral",
                    "timing": {"repeat": repeat},
                    "doseAndRate": [{"doseQuantity": {"value": mg, "unit": "mg"}}],
                }
            ],
            "subject": subject,
        },
        lab(IRON_PANEL),
        lab(FERRITIN),
    ]
