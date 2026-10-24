"""Magnesium repletion in three tiers (two IV, one oral with a paired repeat level) and a renal hold.

Oracle (needs), judge (accurate) and hand-coded rule script (rule_payloads) for this protocol. Analysis code only.
Data adaptation: no newest MG in the 24 hour window is below 1.6 mg/dL, so the tier cut points sit at 1.7, 1.9 and 2.0.
The benchmark has no oral magnesium NDC and no magnesium LOINC, so the two codes below are stated by the text only.
No "magnesium order already active" exclusion: every MedicationRequest in the data is status active with free-text
names and no codes, so an active order cannot be told from an old record.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from heldout import newest  # noqa: E402

from medgate.fhir import FhirClient  # noqa: E402

IV_NDC = "0338-1715-40"
ORAL_NDC = "0904-5105-60"
LAB_LOINC = "19123-9"
EGFR_FLOOR = 50.0
RECHECK_HOURS = 48

PROTOCOL = {
    "name": "Magnesium repletion in tiers",
    "code": "MG",
    "text": (
        "Magnesium repletion protocol (serum magnesium, code MG, drawn in the last 24 hours). By the newest level, "
        "order magnesium with priority routine: below 1.7 mg/dL, IV magnesium sulfate, NDC 0338-1715-40, route IV, "
        "4 g over 4 hours; 1.7 to 1.8 mg/dL, IV magnesium sulfate, NDC 0338-1715-40, route IV, 2 g over 2 hours; "
        "1.9 to 2.0 mg/dL, oral magnesium oxide tablets, NDC 0904-5105-60, route oral, 400 mg twice daily for 2 days. "
        "Record IV doses in g with the duration as a rate in hours, and the oral dose in mg. For the oral tier only, "
        "pair that order with a repeat magnesium level, LOINC 19123-9, priority routine, to be drawn 48 hours after "
        "the order is written; the IV tiers have no repeat level. If the level is above 2.0 mg/dL, order nothing. "
        "Exclusion: before ordering, check the newest eGFR (code EGFR). If it is below 50 mL/min/1.73m2, do not order "
        "magnesium; hold it for pharmacist review."
    ),
}


def _tier(mg: float) -> str | None:
    """'iv4', 'iv2', 'oral', or None (no order) for a magnesium level in mg/dL."""
    return "iv4" if mg < 1.7 else "iv2" if mg < 1.9 else "oral" if mg < 2.05 else None


def needs(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    """What the text requires for this patient, or None if there is no fresh magnesium or no eGFR to check."""
    level = newest(fhir, mrn, "MG", now)
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
    return {"orders": 2 if tier == "oral" else 1, "held": False, "value": value, "egfr": egfr[0], "tier": tier}


# --- the judge ---
def _d(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _first(x: Any) -> dict[str, Any]:
    return _d(x[0]) if isinstance(x, list) and x else {}


def _code(p: dict[str, Any], field: str) -> str:
    return str(_first(_d(p.get(field)).get("coding")).get("code", "")).strip()


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, int | float) and not isinstance(x, bool) else None


def _unit(q: dict[str, Any]) -> str:
    return str(q.get("unit") or q.get("code") or "").strip().lower().replace(" ", "")


def _route(p: dict[str, Any]) -> str:
    route = _first(p.get("dosageInstruction")).get("route")
    r = _d(route)
    text = r.get("text") or _first(r.get("coding")).get("display") or _first(r.get("coding")).get("code") or route
    text = str(text if isinstance(text, str) else "").strip().lower()
    return (
        "iv"
        if text in ("iv", "intravenous", "iv infusion", "iv piggyback")
        else "oral"
        if text in ("oral", "po", "by mouth")
        else text
    )


def _grams(q: Any) -> float | None:
    q = _d(q)
    v, scale = (
        _num(q.get("value")),
        {"g": 1.0, "gram": 1.0, "grams": 1.0, "mg": 0.001, "milligram": 0.001}.get(_unit(q)),
    )
    return None if v is None or scale is None else v * scale


def _hours(q: Any, grams: float) -> float | None:
    """Time in hours implied by a duration or a dose-rate quantity."""
    q = _d(q)
    v, unit = _num(q.get("value")), _unit(q)
    if v is None or v <= 0:
        return None
    if unit in ("h", "hr", "hrs", "hour", "hours"):
        return v
    if unit in ("min", "mins", "minute", "minutes"):
        return v / 60
    per = {"g/h": 1.0, "g/hr": 1.0, "g/min": 60.0, "mg/h": 0.001, "mg/hr": 0.001, "mg/min": 0.06}.get(unit)
    return None if per is None else grams / (v * per)


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
    if "T" not in str(x):
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _twice_daily_two_days(p: dict[str, Any]) -> bool:
    timing = _d(_first(p.get("dosageInstruction")).get("timing"))
    rep = _d(timing.get("repeat"))
    label = str(timing.get("code", {}).get("text", "") if isinstance(timing.get("code"), dict) else "").upper()
    freq, per, pu = rep.get("frequency"), _num(rep.get("period")), str(rep.get("periodUnit", "")).lower()
    twice = (
        (freq == 2 and per == 1 and pu in ("d", "day", "days"))
        or (freq == 2 and per == 24 and pu in ("h", "hour", "hours"))
        or (freq == 1 and per == 12 and pu in ("h", "hour", "hours"))
        or (label in ("BID", "TWICE DAILY", "TWICE A DAY") and not rep.get("frequency"))
    )
    supply = _d(_d(p.get("dispenseRequest")).get("expectedSupplyDuration"))
    spans = [_days(rep.get("boundsDuration")), _days(supply)]
    long_enough = any(s is not None and abs(s - 2) < 0.01 for s in spans) or (rep.get("count") == 4 and freq == 2)
    return bool(twice and long_enough)


def _medication_ok(p: dict[str, Any], tier: str) -> bool:
    if p.get("resourceType") not in (None, "MedicationRequest") or str(p.get("priority", "")).lower() != "routine":
        return False
    oral = tier == "oral"
    if _code(p, "medicationCodeableConcept") != (ORAL_NDC if oral else IV_NDC):
        return False
    if _route(p) != ("oral" if oral else "iv"):
        return False
    dose = _first(_first(p.get("dosageInstruction")).get("doseAndRate"))
    given = _grams(dose.get("doseQuantity"))
    want = 0.4 if oral else 4.0 if tier == "iv4" else 2.0
    if given is None or abs(given - want) > 0.0005:
        return False
    if oral:
        return _twice_daily_two_days(p)
    hours = _hours(dose.get("rateQuantity"), want)
    if hours is None:  # the same time written as the order's duration (timing.repeat.boundsDuration)
        bounds = _d(_d(_d(_first(p.get("dosageInstruction")).get("timing")).get("repeat")).get("boundsDuration"))
        hours = _hours(bounds, want)
    return hours is not None and abs(hours - (4.0 if tier == "iv4" else 2.0)) < 0.01


def _repeat_ok(p: dict[str, Any], due: datetime) -> bool:
    if p.get("resourceType") not in (None, "ServiceRequest") or _code(p, "code") != LAB_LOINC:
        return False
    t = _instant(p.get("occurrenceDateTime"))
    return str(p.get("priority", "")).lower() == "routine" and t is not None and abs((t - due).total_seconds()) < 60


def accurate(need: dict[str, Any], payloads: list[dict[str, Any]], now: datetime) -> bool:
    """Exactly the required orders: the magnesium at this tier's dose and route, plus the repeat level if oral."""
    try:
        if not isinstance(payloads, list):
            return False
        if need["orders"] == 0:
            return not payloads
        if len(payloads) != need["orders"] or not all(isinstance(p, dict) for p in payloads):
            return False
        now = now if now.tzinfo else now.replace(tzinfo=UTC)
        meds = [p for p in payloads if _medication_ok(p, need["tier"])]
        if need["tier"] != "oral":
            return len(meds) == 1
        due = now + timedelta(hours=RECHECK_HOURS)
        return len(meds) == 1 and any(_repeat_ok(p, due) for p in payloads if p is not meds[0])
    except Exception:  # noqa: BLE001 - a malformed payload is a wrong answer, never a crash
        return False


# --- the hand-coded rule script (the baseline) ---
def rule_payloads(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    level, egfr = newest(fhir, mrn, "MG", now), newest(fhir, mrn, "EGFR", now)
    if level is None or level[1] < now - window or _tier(level[0]) is None or egfr is None or egfr[0] < EGFR_FLOOR:
        return []
    tier, subject = str(_tier(level[0])), {"reference": mrn}
    if tier == "oral":
        repeat = {"frequency": 2, "period": 1, "periodUnit": "d", "boundsDuration": {"value": 2, "unit": "d"}}
        return [
            {
                "medicationCodeableConcept": {"coding": [{"code": ORAL_NDC}]},
                "dosageInstruction": [
                    {
                        "route": "oral",
                        "timing": {"repeat": repeat},
                        "doseAndRate": [{"doseQuantity": {"value": 400, "unit": "mg"}}],
                    }
                ],
                "priority": "routine",
                "subject": subject,
            },
            {
                "code": {"coding": [{"code": LAB_LOINC}]},
                "priority": "routine",
                "occurrenceDateTime": (now + timedelta(hours=RECHECK_HOURS)).isoformat(timespec="seconds"),
                "subject": subject,
            },
        ]
    grams = 4 if tier == "iv4" else 2
    dose = {"doseQuantity": {"value": grams, "unit": "g"}, "rateQuantity": {"value": grams, "unit": "h"}}
    return [
        {
            "medicationCodeableConcept": {"coding": [{"code": IV_NDC}]},
            "dosageInstruction": [{"route": "IV", "doseAndRate": [dose]}],
            "priority": "routine",
            "subject": subject,
        }
    ]
