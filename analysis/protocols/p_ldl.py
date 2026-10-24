"""Oral glucose-lowering protocol with a liver exclusion (single order, no recheck).

Slot: "High LDL". The live data has one LDL result inside the 24 hour window (see the data check below), so the
trigger lab is serum glucose (code GLU), the closest variant of the same shape: one oral order, dose by tier,
no recheck, exclusion on an ALT multiple of the upper limit, hold for review.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from heldout import newest  # noqa: E402
from heldout_run import _close, _code, _dict, _first, _route  # noqa: E402

NDC = "68180-0003-01"
ULN_ALT = 40.0  # U/L, as stated in the text

PROTOCOL = {
    "name": "Oral glucose-lowering (LDL slot variant)",
    "code": "GLU",
    "text": (
        "Oral glucose-lowering protocol (serum glucose, code GLU, drawn in the last 24 hours). If the newest "
        "glucose is 140 mg/dL or higher, order oral metformin, NDC 68180-0003-01, route oral, once daily for 3 days, "
        "priority routine: 140 to below 200 mg/dL, 500 mg per dose; 200 mg/dL or higher, 1000 mg per dose. Record "
        "the dose in mg. No repeat glucose is ordered. If the glucose is below 140 mg/dL, order nothing. Exclusion: "
        "before ordering, check the newest ALT (code ALT). The upper limit of normal for ALT is 40 U/L. If the ALT "
        "is above 3 times the upper limit (above 120 U/L), do not order metformin; hold it for pharmacist review."
    ),
}


def needs(fhir: Any, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    glucose = newest(fhir, mrn, "GLU", now)
    if glucose is None or glucose[1] < now - window:
        return None
    value = glucose[0]
    if value < 140:
        return {"orders": 0, "held": False, "value": value}
    alt = newest(fhir, mrn, "ALT", now)
    if alt is None:  # the exclusion cannot be applied
        return None
    if alt[0] > 3 * ULN_ALT:
        return {"orders": 0, "held": True, "value": value, "alt": alt[0]}
    return {"orders": 1, "held": False, "value": value, "mg": 500 if value < 200 else 1000, "alt": alt[0]}


def _mg(dose: dict[str, Any]) -> float | None:
    q = _dict(dose.get("doseQuantity"))
    v, unit = q.get("value"), str(q.get("unit", "")).lower()
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    return (
        float(v)
        if unit in ("mg", "milligram", "milligrams")
        else v * 1000.0
        if unit in ("g", "gram", "grams")
        else None
    )


def _snomed_oral(p: dict[str, Any]) -> bool:
    route = _dict(_first(p.get("dosageInstruction")).get("route"))
    return (
        _code(_first(p.get("dosageInstruction")), "route") == "26643006" or "oral" == str(route.get("text", "")).lower()
    )


def _three_days_once_daily(p: dict[str, Any]) -> bool:
    instr = _first(p.get("dosageInstruction"))
    rep = _dict(_dict(instr.get("timing")).get("repeat"))
    freq, per, pu = rep.get("frequency"), rep.get("period"), str(rep.get("periodUnit", "")).lower()
    daily = (freq, per) == (1, 1) and pu in ("d", "day", "days") or (freq, per, pu) == (1, 24, "h")
    bounds = _dict(rep.get("boundsDuration"))
    bv, bu = bounds.get("value"), str(bounds.get("unit", "")).lower()
    supply = _dict(_dict(p.get("dispenseRequest")).get("expectedSupplyDuration"))
    sv, su = supply.get("value"), str(supply.get("unit", "")).lower()
    days = lambda v, u: _close(v, 3) and u in ("d", "day", "days")  # noqa: E731
    hours = lambda v, u: _close(v, 72) and u in ("h", "hour", "hours")  # noqa: E731
    long_enough = days(bv, bu) or hours(bv, bu) or days(sv, su) or hours(sv, su) or rep.get("count") == 3
    return bool(daily and long_enough)


def accurate(need: dict[str, Any], payloads: list[dict[str, Any]], now: datetime) -> bool:
    try:
        if not isinstance(payloads, list):
            return False
        if int(need["orders"]) == 0:  # no metformin, or held for pharmacist review: nothing may be ordered
            return not payloads
        if int(need["orders"]) != 1 or len(payloads) != 1:  # exactly the one order, no extras or duplicates
            return False
        want = float(need["mg"])
        for p in payloads:
            if not isinstance(p, dict):
                continue
            dose = _first(_first(p.get("dosageInstruction")).get("doseAndRate"))
            amount = _mg(dose)
            if (
                p.get("resourceType", "MedicationRequest") == "MedicationRequest"
                and _code(p, "medicationCodeableConcept") == NDC
                and (_route(p) in ("oral", "po") or _snomed_oral(p))
                and amount is not None
                and _close(amount, want)
                and str(p.get("priority", "")).lower() == "routine"
                and _three_days_once_daily(p)
            ):
                return True
    except Exception:
        return False
    return False


def rule_payloads(fhir: Any, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    glucose, alt = newest(fhir, mrn, "GLU", now), newest(fhir, mrn, "ALT", now)
    if glucose is None or glucose[1] < now - window or glucose[0] < 140 or alt is None or alt[0] > 120:
        return []
    repeat = {"frequency": 1, "period": 1, "periodUnit": "d", "boundsDuration": {"value": 3, "unit": "d"}}
    dose = {"doseQuantity": {"value": 500 if glucose[0] < 200 else 1000, "unit": "mg"}}
    return [
        {
            "medicationCodeableConcept": {"coding": [{"code": NDC}]},
            "dosageInstruction": [{"route": "oral", "timing": {"repeat": repeat}, "doseAndRate": [dose]}],
            "priority": "routine",
            "subject": {"reference": mrn},
        }
    ]
