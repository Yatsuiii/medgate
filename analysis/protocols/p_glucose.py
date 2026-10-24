"""Hypoglycemia protocol: tiered IV dextrose by glucose level, plus a stat glucose recheck 30 minutes after the order.

The oracle (needs), the judge (accurate) and the rule script (rule_payloads) live here, in analysis code. The agent
applies the protocol text and never sees them. The thresholds sit at 90 mg/dL and above because the ward's data holds
no glucose below 73 mg/dL, so a clinical threshold of 70 would give no events.
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from heldout import newest  # noqa: E402

from medgate.protocol import FHIR_BASE  # noqa: E402

DRUG, LAB = "0409-4902-34", "2339-0"

PROTOCOL = {
    "name": "Hypoglycemia dextrose",
    "code": "GLU",
    "text": (
        "Low glucose protocol (serum glucose, code GLU, drawn in the last 24 hours). By the newest glucose, order IV "
        "dextrose 50%, NDC 0409-4902-34, route IV: 85 to below 90 mg/dL, 12.5 g over 5 minutes; 80 to below 85 mg/dL, "
        "25 g over 10 minutes; below 80 mg/dL, 50 g over 15 minutes. Record the dose in g and the duration in minutes "
        "as a rate. Pair that order with a repeat serum glucose level, LOINC 2339-0, priority stat, to be drawn 30 "
        "minutes after the order is written. If the glucose is 90 mg/dL or higher, order nothing."
    ),
}


def tier(glucose: float) -> tuple[float, int] | None:
    """(grams, minutes) for a glucose in mg/dL, or None if the text orders nothing."""
    if glucose >= 90:
        return None
    return (12.5, 5) if glucose >= 85 else (25, 10) if glucose >= 80 else (50, 15)


def needs(fhir: Any, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    found = newest(fhir, mrn, "GLU", now)
    if found is None or found[1] < now - window:
        return None
    dose = tier(found[0])
    if dose is None:
        return {"orders": 0, "held": False, "value": found[0]}
    return {"orders": 2, "held": False, "value": found[0], "grams": dose[0], "minutes": dose[1]}


# --- the judge ---
def _d(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _first(x: Any) -> dict[str, Any]:
    return _d(x[0]) if isinstance(x, list) and x else {}


def _codes(p: dict[str, Any], field: str) -> set[str]:
    """Every code in a CodeableConcept: a re-encoding may carry other systems' codes next to the one we need."""
    coding = _d(p.get(field)).get("coding")
    return {str(c.get("code", "")) for c in coding if isinstance(c, dict)} if isinstance(coding, list) else set()


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, int | float) and not isinstance(x, bool) else None


def _instant(x: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _route_ok(p: dict[str, Any]) -> bool:
    route = _first(p.get("dosageInstruction")).get("route")
    parts = (
        [route]
        if isinstance(route, str)
        else [_d(route).get("text")]
        + [v for c in _d(route).get("coding", []) if isinstance(c, dict) for v in (c.get("code"), c.get("display"))]
    )
    return any(str(s).strip().lower() in ("iv", "intravenous", "iv push") for s in parts if s)


def _grams(q: dict[str, Any]) -> float | None:
    value, unit = _num(q.get("value")), str(q.get("unit", "")).strip().lower()
    scale = {"g": 1, "gram": 1, "grams": 1, "mg": 0.001}.get(unit)
    return None if value is None or scale is None else value * scale


def _minutes(rate: dict[str, Any], grams: float) -> float | None:
    """The infusion duration in minutes from a rate: a bare time unit is a duration, 'g/<time>' is a g rate."""
    value, unit = _num(rate.get("value")), str(rate.get("unit", "")).strip().lower().replace(" ", "")
    per = {"min": 1, "minute": 1, "minutes": 1, "h": 60, "hr": 60, "hour": 60, "hours": 60}
    if value is None:
        return None
    if unit in per:
        return value * per[unit]
    mass, _, time = unit.partition("/")
    if time in per and value > 0 and mass in ("g", "gram", "grams", "mg"):
        return grams / (value * (0.001 if mass == "mg" else 1)) * per[time]
    return None


def _drug_ok(p: dict[str, Any], grams: float, minutes: float) -> bool:
    instruction = _first(p.get("dosageInstruction"))
    dose = _first(instruction.get("doseAndRate"))
    given = _grams(_d(dose.get("doseQuantity")))
    duration = _minutes(_d(dose.get("rateQuantity")), grams)
    if duration is None:  # the same course length written as the order's duration (timing.repeat.boundsDuration)
        duration = _minutes(_d(_d(_d(instruction.get("timing")).get("repeat")).get("boundsDuration")), grams)
    return (
        _route_ok(p)
        and given is not None
        and abs(given - grams) < 0.05
        and duration is not None
        and abs(duration - minutes) < 0.5
    )


def _lab_ok(p: dict[str, Any], now: datetime) -> bool:
    when = _instant(p.get("occurrenceDateTime"))
    due = now + timedelta(minutes=30)
    return str(p.get("priority", "")).lower() == "stat" and when is not None and abs((when - due).total_seconds()) <= 30


def accurate(need: dict[str, Any], payloads: list[Any], now: datetime) -> bool:
    try:
        if need.get("orders") != 2:
            return not payloads
        items = [p for p in payloads if isinstance(p, dict)]
        drugs = [p for p in items if DRUG in _codes(p, "medicationCodeableConcept")]
        labs = [p for p in items if LAB in _codes(p, "code")]
        if len(drugs) != 1 or len(labs) != 1 or len(items) != len(payloads) or len(payloads) != 2:
            return False
        return _drug_ok(drugs[0], float(need["grams"]), float(need["minutes"])) and _lab_ok(labs[0], now)
    except Exception:  # noqa: BLE001 - a malformed payload is a wrong answer, never a crash
        return False


# --- the hand-coded rule script (baseline) ---
def rule_payloads(fhir: Any, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    glucose = newest(fhir, mrn, "GLU", now)
    if glucose is None or glucose[1] < now - window or glucose[0] >= 90:
        return []
    grams, minutes = tier(glucose[0]) or (0, 0)
    entries = json.loads(str(fhir.get(f"{FHIR_BASE}Observation?patient={mrn}&code=GLU&_count=5000&_format=json").data))
    obs = next(
        e["resource"]["id"]
        for e in entries["entry"]
        if e["resource"].get("effectiveDateTime") == glucose[1].isoformat()
    )
    ref = [{"reference": f"Observation/{obs}"}]
    dose = {"doseQuantity": {"value": grams, "unit": "g"}, "rateQuantity": {"value": minutes, "unit": "min"}}
    return [
        {
            "medicationCodeableConcept": {"coding": [{"code": DRUG}]},
            "dosageInstruction": [{"route": "IV", "doseAndRate": [dose]}],
            "subject": {"reference": mrn},
            "reasonReference": ref,
        },
        {
            "code": {"coding": [{"code": LAB}]},
            "priority": "stat",
            "occurrenceDateTime": (now + timedelta(minutes=30)).isoformat(timespec="seconds"),
            "subject": {"reference": mrn},
            "reasonReference": ref,
        },
    ]
