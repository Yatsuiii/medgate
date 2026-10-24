"""IV saline for a high BUN in three tiers, with a paired repeat BUN and a creatinine hold.

Oracle (needs), judge (accurate) and hand-coded rule script (rule_payloads) for this protocol. Analysis code only.
Data adaptation: the server has no sodium above 145 mmol/L in the 24 hour window (and NA belongs to p_sodium), so this
protocol uses the high-value lab BUN (urea nitrogen, code BUN) instead of hypernatremia, with the fluid tiers sized to
the BUN spread present (40 up to 75+ mg/dL). The fluid NDC and the BUN LOINC 3094-0 are stated by the text only; the
benchmark has no IV fluid NDC. No "fluid already running" exclusion: every MedicationRequest in the data is active with
free-text names and no codes.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from heldout import newest  # noqa: E402

from medgate.fhir import FhirClient  # noqa: E402

FLUID_NDC = "0338-0049-04"
LAB_LOINC = "3094-0"
CR_HOLD = 3.0
RECHECK_HOURS = 12
# tier -> (volume in mL, hours)
TIERS = {"low": (500.0, 4.0), "mid": (1000.0, 8.0), "high": (1000.0, 4.0)}

PROTOCOL = {
    "name": "IV saline for high BUN",
    "code": "BUN",
    "text": (
        "High urea nitrogen protocol (serum BUN, code BUN, drawn in the last 24 hours). By the newest BUN, order IV "
        "0.9% sodium chloride, NDC 0338-0049-04, route IV, priority urgent: 40 to 49 mg/dL, 500 mL over 4 hours; "
        "50 to 69 mg/dL, 1000 mL over 8 hours; 70 mg/dL or higher, 1000 mL over 4 hours. Record the volume in mL and "
        "the duration as a rate in hours. Pair every fluid order with a repeat BUN, LOINC 3094-0, priority routine, "
        "to be drawn 12 hours after the order is written. If the BUN is below 40 mg/dL, order nothing. Exclusion: "
        "before ordering, check the newest creatinine (code CR). If it is 3.0 mg/dL or higher, do not order fluid or "
        "the repeat BUN; hold it for nephrology review."
    ),
}


def _tier(bun: float) -> str | None:
    """'low', 'mid', 'high', or None (no order) for a BUN in mg/dL."""
    return "high" if bun >= 70 else "mid" if bun >= 50 else "low" if bun >= 40 else None


def needs(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    """What the text requires for this patient, or None if there is no fresh BUN or no creatinine to check."""
    level = newest(fhir, mrn, "BUN", now)
    if level is None or level[1] < now - window:
        return None
    value, tier = level[0], _tier(level[0])
    if tier is None:
        return {"orders": 0, "held": False, "value": value}
    cr = newest(fhir, mrn, "CR", now)
    if cr is None:
        return None
    if cr[0] >= CR_HOLD:
        return {"orders": 0, "held": True, "value": value, "cr": cr[0]}
    return {"orders": 2, "held": False, "value": value, "cr": cr[0], "tier": tier}


# --- the judge ---
def _d(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _first(x: Any) -> dict[str, Any]:
    return _d(x[0]) if isinstance(x, list) and x else {}


def _codes(p: dict[str, Any], field: str) -> list[str]:
    coding = _d(p.get(field)).get("coding")
    return [str(c.get("code", "")).strip() for c in coding if isinstance(c, dict)] if isinstance(coding, list) else []


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, int | float) and not isinstance(x, bool) else None


def _unit(q: dict[str, Any]) -> str:
    return str(q.get("unit") or q.get("code") or "").strip().lower().replace(" ", "")


def _route(p: dict[str, Any]) -> str:
    route = _first(p.get("dosageInstruction")).get("route")
    r = _d(route)
    text = r.get("text") or _first(r.get("coding")).get("display") or _first(r.get("coding")).get("code") or route
    text = str(text if isinstance(text, str) else "").strip().lower()
    return "iv" if text in ("iv", "intravenous", "iv infusion") else text


def _ml(q: Any) -> float | None:
    q = _d(q)
    v, scale = (
        _num(q.get("value")),
        {"ml": 1.0, "milliliter": 1.0, "milliliters": 1.0, "l": 1000.0, "liter": 1000.0}.get(_unit(q)),
    )
    return None if v is None or scale is None else v * scale


def _hours(q: Any, ml: float) -> float | None:
    """Time in hours implied by a duration or a volume-rate quantity."""
    q = _d(q)
    v, unit = _num(q.get("value")), _unit(q)
    if v is None or v <= 0:
        return None
    if unit in ("h", "hr", "hrs", "hour", "hours"):
        return v
    if unit in ("min", "mins", "minute", "minutes"):
        return v / 60
    per = {"ml/h": 1.0, "ml/hr": 1.0, "ml/min": 60.0, "l/h": 1000.0, "l/hr": 1000.0}.get(unit)
    return None if per is None else ml / (v * per)


def _instant(x: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except ValueError:
        return None
    if "T" not in str(x):
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _fluid_ok(p: dict[str, Any], tier: str) -> bool:
    if p.get("resourceType") not in (None, "MedicationRequest") or str(p.get("priority", "")).lower() != "urgent":
        return False
    if FLUID_NDC not in _codes(p, "medicationCodeableConcept") or _route(p) != "iv":
        return False
    want_ml, want_h = TIERS[tier]
    dose = _first(_first(p.get("dosageInstruction")).get("doseAndRate"))
    given = _ml(dose.get("doseQuantity"))
    if given is None or abs(given - want_ml) > 0.5:
        return False
    hours = _hours(dose.get("rateQuantity"), want_ml)
    if hours is None:  # the same time written as the order's duration (timing.repeat.boundsDuration)
        bounds = _d(_d(_d(_first(p.get("dosageInstruction")).get("timing")).get("repeat")).get("boundsDuration"))
        hours = _hours(bounds, want_ml)
    return hours is not None and abs(hours - want_h) < 0.01


def _repeat_ok(p: dict[str, Any], due: datetime) -> bool:
    if p.get("resourceType") not in (None, "ServiceRequest") or LAB_LOINC not in _codes(p, "code"):
        return False
    t = _instant(p.get("occurrenceDateTime"))
    return str(p.get("priority", "")).lower() == "routine" and t is not None and abs((t - due).total_seconds()) < 60


def accurate(need: dict[str, Any], payloads: list[dict[str, Any]], now: datetime) -> bool:
    """Exactly two orders: the saline at this tier's volume, route and duration, plus the repeat BUN."""
    try:
        if not isinstance(payloads, list):
            return False
        if need["orders"] == 0:
            return not payloads
        if len(payloads) != need["orders"] or not all(isinstance(p, dict) for p in payloads):
            return False
        now = now if now.tzinfo else now.replace(tzinfo=UTC)
        meds = [p for p in payloads if _fluid_ok(p, need["tier"])]
        due = now + timedelta(hours=RECHECK_HOURS)
        return len(meds) == 1 and any(_repeat_ok(p, due) for p in payloads if p is not meds[0])
    except Exception:  # noqa: BLE001 - a malformed payload is a wrong answer, never a crash
        return False


# --- the hand-coded rule script (the baseline) ---
def rule_payloads(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    level, cr = newest(fhir, mrn, "BUN", now), newest(fhir, mrn, "CR", now)
    if level is None or level[1] < now - window or _tier(level[0]) is None or cr is None or cr[0] >= CR_HOLD:
        return []
    ml, hours = TIERS[str(_tier(level[0]))]
    subject = {"reference": mrn}
    dose = {"doseQuantity": {"value": ml, "unit": "mL"}, "rateQuantity": {"value": hours, "unit": "h"}}
    return [
        {
            "medicationCodeableConcept": {"coding": [{"code": FLUID_NDC}]},
            "dosageInstruction": [{"route": "IV", "doseAndRate": [dose]}],
            "priority": "urgent",
            "subject": subject,
        },
        {
            "code": {"coding": [{"code": LAB_LOINC}]},
            "priority": "routine",
            "occurrenceDateTime": (now + timedelta(hours=RECHECK_HOURS)).isoformat(timespec="seconds"),
            "subject": subject,
        },
    ]
