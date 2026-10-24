"""Hyponatremia protocol: oral sodium chloride tiered by level, no recheck, held when the newest glucose is high.

The oracle (needs), the judge (accurate) and the rule script (rule_payloads) live here, in analysis code. The agent
applies PROTOCOL["text"] and never sees them. Nothing here touches the network at import.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from heldout import newest  # noqa: E402

NDC = "0904-6301-60"
HIGH_GLUCOSE = 200  # mg/dL

PROTOCOL = {
    "name": "Hyponatremia sodium chloride",
    "code": "NA",
    "text": (
        "Hyponatremia protocol (serum sodium, code NA, drawn in the last 24 hours). If the newest sodium is below "
        "135 mmol/L, order oral sodium chloride tablets, NDC 0904-6301-60, route oral, by level: 130 to below "
        "135 mmol/L, 1 g twice daily for 2 days; 126 to below 130 mmol/L, 1 g three times daily for 3 days; below "
        "126 mmol/L, 2 g three times daily for 3 days. Record the dose in g per administration, the frequency as "
        "administrations per day, and the duration in days. No repeat level is ordered. If the sodium is 135 "
        "mmol/L or higher, order nothing. Exclusion: before ordering, check the newest glucose (code GLU). If it "
        "is 200 mg/dL or higher, the low sodium may reflect high glucose: do not order, hold it for pharmacist "
        "review."
    ),
}


def regimen(sodium: float) -> tuple[float, int, int]:
    """(grams per administration, administrations per day, days) for a sodium below 135."""
    if sodium >= 130:
        return 1, 2, 2
    return (1, 3, 3) if sodium >= 126 else (2, 3, 3)


def needs(fhir: Any, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    na = newest(fhir, mrn, "NA", now)
    if na is None or na[1] < now - window:
        return None
    if na[0] >= 135:
        return {"orders": 0, "held": False, "value": na[0]}
    glucose = newest(fhir, mrn, "GLU", now)
    if glucose is None:  # the exclusion cannot be checked
        return None
    held = glucose[0] >= HIGH_GLUCOSE
    grams, per_day, days = regimen(na[0])
    return {"orders": 0 if held else 1, "held": held, "value": na[0], "grams": grams, "per_day": per_day, "days": days}


def _d(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _first(x: Any) -> dict[str, Any]:
    return _d(x[0]) if isinstance(x, list) and x else {}


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, int | float) and not isinstance(x, bool) else None


def _hours(unit: Any) -> float | None:
    return {"h": 1, "hr": 1, "hour": 1, "hours": 1, "d": 24, "day": 24, "days": 24}.get(str(unit).strip().lower())


def _oral(route: Any) -> bool:
    if isinstance(route, str):  # the order tool takes the route as plain text; the product converts it on commit
        route = {"text": route}
    route = _d(route)
    words = [str(route.get("text", ""))] + [
        str(c.get(k, "")) for c in map(_d, route.get("coding") or []) for k in ("code", "display")
    ]
    return any(w.strip().lower() in {"oral", "po", "by mouth", "26643006"} for w in words)


def _per_day(timing: dict[str, Any]) -> float | None:
    repeat = _d(timing.get("repeat"))
    freq, period, unit = _num(repeat.get("frequency")), _num(repeat.get("period")), _hours(repeat.get("periodUnit"))
    if freq and period and unit:
        return freq * 24 / (period * unit)
    named = {"bid": 2, "tid": 3}
    texts = [str(timing.get("code", {}).get("text", "")) if isinstance(timing.get("code"), dict) else ""]
    texts += [str(_d(c).get("code", "")) for c in _d(timing.get("code")).get("coding") or []]
    return next((named[t.strip().lower()] for t in texts if t.strip().lower() in named), None)


def _days(payload: dict[str, Any], timing: dict[str, Any]) -> float | None:
    bounds = _d(_d(timing.get("repeat")).get("boundsDuration"))
    supply = _d(_d(payload.get("dispenseRequest")).get("expectedSupplyDuration"))
    for q in (bounds, supply):
        value, unit = _num(q.get("value")), _hours(q.get("unit"))
        if value is not None and unit:
            return value * unit / 24
    return None


def _grams(dose: dict[str, Any]) -> float | None:
    q = _d(dose.get("doseQuantity"))
    value, unit = _num(q.get("value")), str(q.get("unit", "")).strip().lower()
    if value is None:
        return None
    return value if unit in {"g", "gram", "grams"} else value / 1000 if unit == "mg" else None


def _matches(p: Any, need: dict[str, Any]) -> bool:
    p = _d(p)
    inst = _first(p.get("dosageInstruction"))
    codes = {
        str(_d(c).get("code", "")).replace("-", "") for c in _d(p.get("medicationCodeableConcept")).get("coding") or []
    }
    timing = _d(inst.get("timing"))
    repeat = _d(timing.get("repeat"))
    # one live, scheduled order: not cancelled or a proposal, not PRN, no second dose, no count/day/time restriction
    single = (
        len(p.get("dosageInstruction") or []) == 1
        and len(inst.get("doseAndRate") or []) == 1
        and p.get("status", "active") in {"active", "on-hold", "draft"}
        and p.get("intent", "order") in {"order", "original-order", "plan"}
        and not inst.get("asNeededBoolean")
        and "asNeededCodeableConcept" not in inst
        and not {"count", "countMax", "dayOfWeek", "timeOfDay", "when", "offset"} & repeat.keys()
    )
    grams, per_day, days = _grams(_first(inst.get("doseAndRate"))), _per_day(timing), _days(p, timing)
    return (
        single
        and p.get("resourceType") in (None, "MedicationRequest")
        and NDC.replace("-", "") in codes
        and _oral(inst.get("route"))
        and grams is not None
        and abs(grams - need["grams"]) < 0.01
        and per_day is not None
        and abs(per_day - need["per_day"]) < 0.01
        and days is not None
        and abs(days - need["days"]) < 0.01
    )


def accurate(need: dict[str, Any], payloads: list[dict[str, Any]], now: datetime) -> bool:
    try:
        return len(payloads) == 1 and _matches(payloads[0], need)
    except Exception:
        return False


def rule_payloads(fhir: Any, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    need = needs(fhir, mrn, now, window)
    if not need or not need["orders"]:
        return []
    repeat = {"frequency": need["per_day"], "period": 1, "periodUnit": "d"}
    repeat["boundsDuration"] = {"value": need["days"], "unit": "d"}  # type: ignore[assignment]
    return [
        {
            "resourceType": "MedicationRequest",
            "medicationCodeableConcept": {"coding": [{"code": NDC}]},
            "dosageInstruction": [
                {
                    "route": {"text": "oral"},
                    "timing": {"repeat": repeat},
                    "doseAndRate": [{"doseQuantity": {"value": need["grams"], "unit": "g"}}],
                }
            ],
            "subject": {"reference": mrn},
        }
    ]
