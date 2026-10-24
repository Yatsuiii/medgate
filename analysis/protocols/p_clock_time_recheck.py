"""Low serum bicarbonate: one urgent oral dose by tier, paired with a recheck at an ABSOLUTE clock time.

Oracle (needs), judge (accurate) and hand-coded rule script (rule_payloads) for this protocol. Analysis code only.
Data adaptation: the trigger is CO2 (serum bicarbonate), a code no other module uses. With 24 hour results thresholds
of 17 and 20 mmol/L give two tiers; eGFR below 30 holds the order.
The benchmark has no sodium bicarbonate NDC and no bicarbonate LOINC order code, so the NDC below is an invented code
and the LOINC (1963-8, bicarbonate in serum or plasma) is a real code, both stated by the text only.
The recheck is due at 06:00 on the next calendar day, in the offset of the ward clock (UTC here), not a number of hours
after the order. Judge: an offset-less date-time is read as UTC; a date-only value fails.
"""

import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from heldout import newest  # noqa: E402

from medgate.fhir import FhirClient  # noqa: E402

NDC = "0904-6556-60"
LAB_LOINC = "1963-8"
EGFR_FLOOR = 30.0
SEVERE_BELOW, MILD_UPTO = 17.0, 20.0
DOSE_MG = {"severe": 1300.0, "mild": 650.0}

PROTOCOL = {
    "name": "Low bicarbonate correction with next-morning recheck",
    "code": "CO2",
    "text": (
        "Low bicarbonate protocol (serum bicarbonate, code CO2, drawn in the last 24 hours). By the newest level, "
        "order oral sodium bicarbonate tablets, NDC 0904-6556-60, route oral, priority urgent, a single dose given "
        "once: below 17 mmol/L, 1300 mg; 17 to 20 mmol/L inclusive, 650 mg. Record the dose in mg. Pair that order "
        "with a repeat serum bicarbonate level, LOINC 1963-8, priority routine, to be drawn at an absolute clock time: "
        "the next calendar day at 06:00 UTC (the ward clock runs in UTC), not a number of hours after the order. "
        "Write that time as a full ISO date-time with the date and the time, for example 2023-11-14T06:00:00+00:00 "
        "if the orders are written on 2023-11-13. If the bicarbonate is above 20 mmol/L, order nothing. Exclusion: "
        "before ordering, check the newest eGFR (code EGFR). If it is below 30 mL/min/1.73m2, do not order "
        "bicarbonate or the recheck; hold both for nephrology review."
    ),
}


def _tier(co2: float) -> str | None:
    return "severe" if co2 < SEVERE_BELOW else "mild" if co2 <= MILD_UPTO else None


def recheck_time(now: datetime) -> datetime:
    """06:00 on the calendar day after `now`, in now's own offset (UTC if it has none)."""
    now = now if now.tzinfo else now.replace(tzinfo=UTC)
    return datetime.combine(now.date() + timedelta(days=1), time(6, 0), tzinfo=now.tzinfo)


def needs(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    """What the text requires for this patient, or None if there is no fresh CO2 or no eGFR to check."""
    level = newest(fhir, mrn, "CO2", now)
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
    return {"orders": 2, "held": False, "value": value, "egfr": egfr[0], "tier": tier}


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
    return "oral" if text in ("oral", "po", "by mouth") else text


def _mg(q: Any) -> float | None:
    q = _d(q)
    v = _num(q.get("value"))
    scale = {"mg": 1.0, "milligram": 1.0, "milligrams": 1.0, "g": 1000.0, "gram": 1000.0, "grams": 1000.0}.get(_unit(q))
    return None if v is None or scale is None else v * scale


def _once(p: dict[str, Any]) -> bool:
    """A single dose: repeat.count of 1, a once/single-dose label or text, or a single-dose dispense of one."""
    di = _first(p.get("dosageInstruction"))
    timing = _d(di.get("timing"))
    rep = _d(timing.get("repeat"))
    label = str(_d(timing.get("code")).get("text", "")).strip().lower()
    code = str(_first(_d(timing.get("code")).get("coding")).get("code", "")).strip().lower()
    text = str(di.get("text", "")).lower()
    if di.get("asNeeded") is True or (_num(rep.get("count")) not in (None, 1.0)):
        return False
    return bool(
        _num(rep.get("count")) == 1.0
        or label in ("once", "one time", "x1", "single dose", "stat")
        or code in ("once", "st", "x1", "stat")
        or any(w in text for w in ("once", "one time", "single dose", "x1"))
    )


def _instant(x: Any) -> datetime | None:
    if not isinstance(x, str) or "T" not in x:
        return None
    try:
        t = datetime.fromisoformat(x.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _medication_ok(p: dict[str, Any], tier: str) -> bool:
    if p.get("resourceType") not in (None, "MedicationRequest") or str(p.get("priority", "")).lower() != "urgent":
        return False
    if _code(p, "medicationCodeableConcept") != NDC or _route(p) != "oral" or not _once(p):
        return False
    dose = _first(_first(p.get("dosageInstruction")).get("doseAndRate"))
    given = _mg(dose.get("doseQuantity"))
    return given is not None and abs(given - DOSE_MG[tier]) < 0.5


def _recheck_ok(p: dict[str, Any], due: datetime) -> bool:
    if p.get("resourceType") not in (None, "ServiceRequest") or _code(p, "code") != LAB_LOINC:
        return False
    t = _instant(p.get("occurrenceDateTime"))
    return str(p.get("priority", "")).lower() == "routine" and t is not None and abs((t - due).total_seconds()) < 60


def accurate(need: dict[str, Any], payloads: list[dict[str, Any]], now: datetime) -> bool:
    """Exactly two orders: the tier's dose once, orally, urgent, and the recheck at 06:00 on the next calendar day."""
    try:
        if not isinstance(payloads, list):
            return False
        if need["orders"] == 0:
            return not payloads
        if len(payloads) != need["orders"] or not all(isinstance(p, dict) for p in payloads):
            return False
        meds = [p for p in payloads if _medication_ok(p, need["tier"])]
        due = recheck_time(now)
        return len(meds) == 1 and any(_recheck_ok(p, due) for p in payloads if p is not meds[0])
    except Exception:  # noqa: BLE001 - a malformed payload is a wrong answer, never a crash
        return False


# --- the hand-coded rule script (the baseline) ---
def rule_payloads(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    level, egfr = newest(fhir, mrn, "CO2", now), newest(fhir, mrn, "EGFR", now)
    if level is None or level[1] < now - window or _tier(level[0]) is None or egfr is None or egfr[0] < EGFR_FLOOR:
        return []
    subject = {"reference": mrn}
    dose = int(DOSE_MG[str(_tier(level[0]))])
    return [
        {
            "resourceType": "MedicationRequest",
            "medicationCodeableConcept": {"coding": [{"code": NDC}]},
            "dosageInstruction": [
                {
                    "route": "oral",
                    "timing": {"repeat": {"count": 1}},
                    "doseAndRate": [{"doseQuantity": {"value": dose, "unit": "mg"}}],
                }
            ],
            "priority": "urgent",
            "subject": subject,
        },
        {
            "resourceType": "ServiceRequest",
            "code": {"coding": [{"system": "http://loinc.org", "code": LAB_LOINC}]},
            "priority": "routine",
            "occurrenceDateTime": recheck_time(now).isoformat(timespec="seconds"),
            "subject": subject,
        },
    ]
