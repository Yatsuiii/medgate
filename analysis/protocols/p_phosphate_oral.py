"""Oral phosphate repletion in two dose tiers (three times daily for 3 days, no recheck) with a renal hold.

Oracle (needs), judge (accurate) and hand-coded rule script (rule_payloads) for this protocol. Analysis code only.
Trigger lab is serum phosphorus (PHOS), newest value in the 24 hour window. Hold lab is the newest eGFR (EGFR), taken
as the newest on record like the magnesium module does.
Data adaptation: in the 24 hour window only one PHOS is below 2.0 mg/dL, so the tiers are below 2.5 and 2.5 to 2.8.
The benchmark has no phosphate NDC; the NDC below is invented and stated by the text only.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from heldout import newest  # noqa: E402

from medgate.fhir import FhirClient  # noqa: E402

NDC = "0095-0183-01"  # invented
EGFR_FLOOR = 45.0
HIGH_BELOW, LOW_UPTO = 2.5, 2.8  # high tier: PHOS < 2.5; low tier: 2.5 <= PHOS <= 2.8
DOSE_MG = {"high": 500.0, "low": 250.0}

PROTOCOL = {
    "name": "Oral phosphate repletion",
    "code": "PHOS",
    "text": (
        "Oral phosphate protocol (serum phosphorus, code PHOS, drawn in the last 24 hours). By the newest level, "
        "order oral phosphate tablets (sodium and potassium phosphate), NDC 0095-0183-01, route oral, priority "
        "routine, 3 times daily for 3 days: below 2.5 mg/dL, 500 mg of phosphorus per dose; 2.5 to 2.8 mg/dL, "
        "250 mg of phosphorus per dose. Record the dose in mg, the frequency as 3 times a day and the course length "
        "as 3 days. No repeat level is ordered. If the level is above 2.8 mg/dL, order nothing. Exclusion: before "
        "ordering, check the newest eGFR (code EGFR). If it is below 45 mL/min/1.73m2, do not order phosphate; hold "
        "it for pharmacist review."
    ),
}


def _tier(phos: float) -> str | None:
    return "high" if phos < HIGH_BELOW else "low" if phos < LOW_UPTO + 0.05 else None


def needs(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    """What the text requires for this patient, or None if there is no fresh phosphorus or no eGFR to check."""
    level = newest(fhir, mrn, "PHOS", now)
    if level is None or level[1] < now - window:
        return None
    value, tier = level[0], _tier(level[0])
    if tier is None:
        return {"orders": 0, "held": False, "value": value}
    egfr = newest(fhir, mrn, "EGFR", now)
    if egfr is None:
        return None
    if egfr[0] < EGFR_FLOOR:
        return {"orders": 0, "held": True, "value": value, "egfr": egfr[0]}
    return {"orders": 1, "held": False, "value": value, "egfr": egfr[0], "tier": tier}


# --- the judge ---
def _d(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _first(x: Any) -> dict[str, Any]:
    return _d(x[0]) if isinstance(x, list) and x else {}


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, int | float) and not isinstance(x, bool) else None


def _unit(q: dict[str, Any]) -> str:
    return str(q.get("unit") or q.get("code") or "").strip().lower().replace(" ", "")


def _med_code(p: dict[str, Any]) -> str:
    concept = _d(p.get("medicationCodeableConcept"))
    return str(_first(concept.get("coding")).get("code", "")).strip()


def _route(p: dict[str, Any]) -> str:
    route = _first(p.get("dosageInstruction")).get("route")
    r = _d(route)
    coding = _first(r.get("coding"))
    text = r.get("text") or coding.get("display") or coding.get("code") or route
    text = str(text if isinstance(text, str) else "").strip().lower()
    return "oral" if text in ("oral", "po", "by mouth", "per os", "26643006", "oral route") else text


def _mg(q: Any) -> float | None:
    q = _d(q)
    v, scale = (
        _num(q.get("value")),
        {"mg": 1.0, "milligram": 1.0, "milligrams": 1.0, "g": 1000.0, "gram": 1000.0}.get(_unit(q)),
    )
    return None if v is None or scale is None else v * scale


def _days(q: Any) -> float | None:
    q = _d(q)
    v, unit = _num(q.get("value")), _unit(q)
    scale = {"d": 1.0, "day": 1.0, "days": 1.0, "h": 1 / 24, "hr": 1 / 24, "hour": 1 / 24, "hours": 1 / 24}.get(unit)
    return None if v is None or scale is None else v * scale


def _instant(x: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _tid_three_days(p: dict[str, Any]) -> bool:
    timing = _d(_first(p.get("dosageInstruction")).get("timing"))
    rep = _d(timing.get("repeat"))
    code = timing.get("code")
    label = str(_d(code).get("text", "")).upper()
    freq, per, pu = rep.get("frequency"), _num(rep.get("period")), str(rep.get("periodUnit", "")).lower()
    tid = (
        (freq == 3 and per == 1 and pu in ("d", "day", "days"))
        or (freq == 3 and per == 24 and pu in ("h", "hour", "hours"))
        or (freq == 1 and per == 8 and pu in ("h", "hour", "hours"))
        or (label in ("TID", "THREE TIMES DAILY", "3 TIMES DAILY", "3 TIMES A DAY") and not rep.get("frequency"))
    )
    supply = _d(_d(p.get("dispenseRequest")).get("expectedSupplyDuration"))
    spans = [_days(rep.get("boundsDuration")), _days(supply)]
    period = _d(rep.get("boundsPeriod"))
    start, end = _instant(period.get("start")), _instant(period.get("end"))
    if start is not None and end is not None:
        spans.append((end - start).total_seconds() / 86400)
    long_enough = any(s is not None and abs(s - 3) < 0.01 for s in spans) or (rep.get("count") == 9 and freq == 3)
    return bool(tid and long_enough)


def _medication_ok(p: dict[str, Any], tier: str) -> bool:
    if p.get("resourceType") not in (None, "MedicationRequest") or str(p.get("priority", "")).lower() != "routine":
        return False
    if _med_code(p) != NDC or _route(p) != "oral":
        return False
    dose = _first(_first(p.get("dosageInstruction")).get("doseAndRate"))
    given = _mg(dose.get("doseQuantity"))
    if given is None or abs(given - DOSE_MG[tier]) > 0.5:
        return False
    return _tid_three_days(p)


def accurate(need: dict[str, Any], payloads: list[dict[str, Any]], now: datetime) -> bool:
    """Exactly one oral phosphate order at this tier's dose, frequency and course length, and no other order."""
    try:
        if not isinstance(payloads, list):
            return False
        if need["orders"] == 0:
            return not payloads
        return len(payloads) == 1 and isinstance(payloads[0], dict) and _medication_ok(payloads[0], need["tier"])
    except Exception:  # noqa: BLE001 - a malformed payload is a wrong answer, never a crash
        return False


# --- the hand-coded rule script (the baseline) ---
def rule_payloads(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    level, egfr = newest(fhir, mrn, "PHOS", now), newest(fhir, mrn, "EGFR", now)
    if level is None or level[1] < now - window or _tier(level[0]) is None or egfr is None or egfr[0] < EGFR_FLOOR:
        return []
    tier = str(_tier(level[0]))
    repeat = {"frequency": 3, "period": 1, "periodUnit": "d", "boundsDuration": {"value": 3, "unit": "d"}}
    return [
        {
            "medicationCodeableConcept": {"coding": [{"code": NDC}]},
            "dosageInstruction": [
                {
                    "route": "oral",
                    "timing": {"repeat": repeat},
                    "doseAndRate": [{"doseQuantity": {"value": int(DOSE_MG[tier]), "unit": "mg"}}],
                }
            ],
            "priority": "routine",
            "subject": {"reference": mrn},
        }
    ]
