"""Low chloride: a tiered oral sodium chloride order plus a stat lab for every order, a timed lab for the severe tier.

Oracle (needs), judge (accurate) and hand-coded rule script (rule_payloads) for this protocol. Analysis code only.
Trigger lab is serum chloride (CL), unused by any other module. Data adaptation: thresholds are set so that of the
chloride results in the window, 7 land in the standard tier (95 to 97), 3 in the severe tier (below 95) and 4 more
severe-range patients are held by eGFR below 30; the rest are 98 or higher.
The benchmark has no sodium chloride NDC, so the NDC below is invented and stated by the text only; the two LOINC
codes are real (basic metabolic panel, serum chloride).
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from heldout import newest  # noqa: E402

from medgate.fhir import FhirClient  # noqa: E402

NDC = "0904-7320-60"
STAT_LOINC = "51990-0"
RECHECK_LOINC = "2075-0"
EGFR_FLOOR = 30.0
RECHECK_HOURS = 24

PROTOCOL = {
    "name": "Low chloride replacement",
    "code": "CL",
    "text": (
        "Low chloride protocol (serum chloride, code CL, drawn in the last 24 hours). By the newest chloride, order "
        "oral sodium chloride tablets, NDC 0904-7320-60, route oral, priority routine, twice daily for 5 days: 95 to "
        "97 mmol/L, 1000 mg per dose; below 95 mmol/L, 2000 mg per dose. Record the dose in mg. Every medication "
        "order is paired with a stat lab: a basic metabolic panel, LOINC 51990-0, a ServiceRequest with priority stat, "
        "to be drawn now (the time the orders are written), as an ISO date-time. For the below-95 tier only, also "
        "place a third order: a repeat serum chloride, LOINC 2075-0, a ServiceRequest with priority routine, to be "
        "drawn 24 hours after the orders are written; the 95 to 97 tier has no repeat chloride. If the chloride is "
        "98 or higher, order nothing. Exclusion: before ordering, check the newest eGFR (code EGFR). If it is below "
        "30 mL/min/1.73m2, do not order any of these; hold them for nephrology review."
    ),
}


def _tier(cl: float) -> str | None:
    return "severe" if cl < 95 else "std" if cl < 98 else None


def needs(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    """What the text requires for this patient, or None if there is no fresh chloride or no eGFR to check."""
    level = newest(fhir, mrn, "CL", now)
    if level is None or level[1] < now - window:
        return None
    tier = _tier(level[0])
    if tier is None:
        return {"orders": 0, "held": False, "value": level[0]}
    egfr = newest(fhir, mrn, "EGFR", now)
    if egfr is None:
        return None
    if egfr[0] < EGFR_FLOOR:
        return {"orders": 0, "held": True, "value": level[0], "egfr": egfr[0]}
    return {
        "orders": 3 if tier == "severe" else 2,
        "held": False,
        "value": level[0],
        "egfr": egfr[0],
        "tier": tier,
    }


# --- the judge ---
def _d(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _first(x: Any) -> dict[str, Any]:
    return _d(x[0]) if isinstance(x, list) and x else {}


def _codes(p: dict[str, Any], field: str) -> set[str]:
    coding = _d(p.get(field)).get("coding")
    return {str(_d(c).get("code", "")).strip() for c in coding} if isinstance(coding, list) else set()


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, int | float) and not isinstance(x, bool) else None


def _unit(q: dict[str, Any]) -> str:
    return str(q.get("unit") or q.get("code") or "").strip().lower().replace(" ", "")


def _route(p: dict[str, Any]) -> str:
    route = _first(p.get("dosageInstruction")).get("route")
    r = _d(route)
    text = r.get("text") or _first(r.get("coding")).get("display") or _first(r.get("coding")).get("code") or route
    text = str(text if isinstance(text, str) else "").strip().lower()
    return "oral" if text in ("oral", "po", "by mouth", "per os") else text


def _milligrams(q: Any) -> float | None:
    q = _d(q)
    v = _num(q.get("value"))
    scale = {"mg": 1.0, "milligram": 1.0, "milligrams": 1.0, "g": 1000.0, "gram": 1000.0, "grams": 1000.0}.get(_unit(q))
    return None if v is None or scale is None else v * scale


def _days(q: Any) -> float | None:
    q = _d(q)
    v, unit = _num(q.get("value")), _unit(q)
    scale = {"d": 1.0, "day": 1.0, "days": 1.0, "h": 1 / 24, "hr": 1 / 24, "hour": 1 / 24, "hours": 1 / 24}.get(unit)
    return None if v is None or scale is None else v * scale


def _instant(x: Any) -> datetime | None:
    if not isinstance(x, str) or "T" not in x:
        return None
    try:
        t = datetime.fromisoformat(x.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _twice_daily_five_days(p: dict[str, Any]) -> bool:
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
    bounds = _d(rep.get("boundsPeriod"))
    start, end = _instant(bounds.get("start")), _instant(bounds.get("end"))
    span = (end - start).total_seconds() / 86400 if start and end else None
    spans = [_days(rep.get("boundsDuration")), _days(supply), span]
    long_enough = any(s is not None and abs(s - 5) < 0.01 for s in spans) or (
        rep.get("count") == 10 and freq in (2, None) and label in ("", "BID", "TWICE DAILY", "TWICE A DAY")
    )
    return bool(twice and long_enough)


def _medication_ok(p: dict[str, Any], tier: str) -> bool:
    if p.get("resourceType") not in (None, "MedicationRequest") or str(p.get("priority", "")).lower() != "routine":
        return False
    if NDC not in _codes(p, "medicationCodeableConcept") or _route(p) != "oral":
        return False
    dose = _first(_first(p.get("dosageInstruction")).get("doseAndRate"))
    given = _milligrams(dose.get("doseQuantity"))
    want = 2000.0 if tier == "severe" else 1000.0
    return given is not None and abs(given - want) < 0.5 and _twice_daily_five_days(p)


def _lab_ok(p: dict[str, Any], code: str, priority: str, due: datetime) -> bool:
    if p.get("resourceType") not in (None, "ServiceRequest") or code not in _codes(p, "code"):
        return False
    t = _instant(p.get("occurrenceDateTime"))
    return str(p.get("priority", "")).lower() == priority and t is not None and abs((t - due).total_seconds()) < 60


def accurate(need: dict[str, Any], payloads: list[dict[str, Any]], now: datetime) -> bool:
    """Exactly the required orders, each once: the tiered oral dose, the stat panel, and the severe-tier repeat."""
    try:
        if not isinstance(payloads, list):
            return False
        if need["orders"] == 0:
            return not payloads
        if len(payloads) != need["orders"] or not all(isinstance(p, dict) for p in payloads):
            return False
        now = now if now.tzinfo else now.replace(tzinfo=UTC)
        left = list(payloads)
        meds = [p for p in left if _medication_ok(p, need["tier"])]
        if len(meds) != 1:
            return False
        left.remove(meds[0])
        wanted = [(STAT_LOINC, "stat", now)]
        if need["tier"] == "severe":
            wanted.append((RECHECK_LOINC, "routine", now + timedelta(hours=RECHECK_HOURS)))
        for code, priority, due in wanted:
            match = next((p for p in left if _lab_ok(p, code, priority, due)), None)
            if match is None:
                return False
            left.remove(match)
        return not left
    except Exception:  # noqa: BLE001 - a malformed payload is a wrong answer, never a crash
        return False


# --- the hand-coded rule script (the baseline) ---
def rule_payloads(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    level, egfr = newest(fhir, mrn, "CL", now), newest(fhir, mrn, "EGFR", now)
    if level is None or level[1] < now - window or _tier(level[0]) is None or egfr is None or egfr[0] < EGFR_FLOOR:
        return []
    severe, subject = _tier(level[0]) == "severe", {"reference": mrn}
    repeat = {"frequency": 2, "period": 1, "periodUnit": "d", "boundsDuration": {"value": 5, "unit": "d"}}

    def lab(code: str, priority: str, at: datetime) -> dict[str, Any]:
        return {
            "resourceType": "ServiceRequest",
            "code": {"coding": [{"system": "http://loinc.org", "code": code}]},
            "priority": priority,
            "occurrenceDateTime": at.isoformat(timespec="seconds"),
            "subject": subject,
        }

    out: list[dict[str, Any]] = [
        {
            "medicationCodeableConcept": {"coding": [{"code": NDC}]},
            "dosageInstruction": [
                {
                    "route": "oral",
                    "timing": {"repeat": repeat},
                    "doseAndRate": [{"doseQuantity": {"value": 2000 if severe else 1000, "unit": "mg"}}],
                }
            ],
            "priority": "routine",
            "subject": subject,
        },
        lab(STAT_LOINC, "stat", now),
    ]
    if severe:
        out.append(lab(RECHECK_LOINC, "routine", now + timedelta(hours=RECHECK_HOURS)))
    return out
