"""Low serum bicarbonate protocol: two medications (oral with frequency and a course in days, IV with an infusion
time in hours) and a repeat lab at a relative time, with a calcium hold.

Oracle (needs), judge (accurate) and hand-coded rule script (rule_payloads) for this protocol. Analysis code only.
Data adaptation: trigger CO2 below 19 mmol/L gives ten patients with a fresh CO2; hold calcium below 7.0 mg/dL
holds two (CO2 17 with CA 6.9, CO2 15 with CA 5.5), so eight need orders.
Invented codes: both NDCs below and the 1963-8 repeat code are stated by the text only; the benchmark has none.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from heldout import newest  # noqa: E402

from medgate.fhir import FhirClient  # noqa: E402

ORAL_NDC, IV_NDC, REPEAT = "0904-6571-60", "0409-6625-02", "1963-8"
TRIGGER, CA_FLOOR = 19.0, 7.0
ORAL_MG, ORAL_DAYS, IV_MEQ, IV_HOURS, RECHECK_HOURS = 1300.0, 3, 50.0, 2.0, 12

PROTOCOL = {
    "name": "Low bicarbonate correction",
    "code": "CO2",
    "text": (
        "Low bicarbonate protocol (serum bicarbonate, code CO2, drawn in the last 24 hours). If the newest CO2 is "
        "below 19 mmol/L, place three orders. First, oral sodium bicarbonate tablet, NDC 0904-6571-60, route oral, "
        "1300 mg twice daily for 3 days; record the dose in mg, the frequency as times per day and the course "
        "length in days. Second, IV sodium bicarbonate 8.4% injection, NDC 0409-6625-02, route IV, 50 mEq over 2 "
        "hours; record the dose in mEq and the duration as a rate in hours. Third, a repeat serum bicarbonate, LOINC "
        "1963-8, priority routine, to be drawn 12 hours after the orders are written. Give the draw time as an ISO "
        "date-time. If the CO2 is 19 or higher, order nothing. Exclusion: before ordering, check the newest "
        "calcium (code CA). If it is below 7.0 mg/dL, do not order any of these; hold them for physician review."
    ),
}


def needs(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    """What the text requires for this patient, or None if there is no fresh CO2 or no calcium to check."""
    level = newest(fhir, mrn, "CO2", now)
    if level is None or level[1] < now - window:
        return None
    if level[0] >= TRIGGER:
        return {"orders": 0, "held": False, "value": level[0]}
    ca = newest(fhir, mrn, "CA", now)
    if ca is None:
        return None
    if ca[0] < CA_FLOOR:
        return {"orders": 0, "held": True, "value": level[0], "ca": ca[0]}
    return {"orders": 3, "held": False, "value": level[0], "ca": ca[0]}


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
        if text in ("iv", "intravenous", "iv push", "iv infusion")
        else "oral"
        if text in ("oral", "po", "by mouth")
        else text
    )


def _mass_mg(q: Any) -> float | None:
    q = _d(q)
    v = _num(q.get("value"))
    scale = {"mg": 1.0, "g": 1000.0, "mcg": 0.001, "ug": 0.001}.get(_unit(q))
    return None if v is None or scale is None else v * scale


def _meq(q: Any) -> float | None:
    q = _d(q)
    v = _num(q.get("value"))
    return v if v is not None and _unit(q) in ("meq", "mmol") else None


def _hours(q: Any, amount: float | None = None) -> float | None:
    """A length of time in hours from a Quantity or Duration; a mEq/h rate is converted with the dose `amount`."""
    q = _d(q)
    v, unit = _num(q.get("value")), _unit(q)
    if v is None or v <= 0:
        return None
    scale = {"h": 1, "hr": 1, "hrs": 1, "hour": 1, "hours": 1, "min": 1 / 60, "mins": 1 / 60, "minute": 1 / 60}
    scale |= {"minutes": 1 / 60, "d": 24, "day": 24, "days": 24}
    if unit in scale:
        return v * scale[unit]
    if amount is not None and unit in ("meq/h", "meq/hr", "mmol/h", "mmol/hr"):
        return amount / v
    return None


def _instant(x: Any) -> datetime | None:
    if not isinstance(x, str) or "T" not in x:
        return None
    try:
        t = datetime.fromisoformat(x.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _per_day(repeat: dict[str, Any], timing: dict[str, Any]) -> float | None:
    """Doses per day from timing.repeat (frequency over period, plus frequencyMax ignored) or a BID code."""
    f, per = _num(repeat.get("frequency")), _num(repeat.get("period"))
    unit = {"h": 1 / 24, "d": 1.0, "wk": 7.0, "min": 1 / 1440}.get(str(repeat.get("periodUnit", "")).strip().lower())
    if f is not None and per is not None and per > 0 and unit is not None:
        return f / (per * unit)
    code = _code(timing, "code") or str(_d(timing.get("code")).get("text", ""))
    return 2.0 if code.strip().lower() in ("bid", "twice daily", "twice a day") else None


def _course_days(repeat: dict[str, Any]) -> float | None:
    h = _hours(repeat.get("boundsDuration"))
    if h is None:
        bounds = _d(repeat.get("boundsPeriod"))
        start, end = _instant(bounds.get("start")), _instant(bounds.get("end"))
        if start is None or end is None:
            return None
        h = (end - start).total_seconds() / 3600
    return h / 24


def _oral_ok(p: dict[str, Any]) -> bool:
    if p.get("resourceType") not in (None, "MedicationRequest") or _code(p, "medicationCodeableConcept") != ORAL_NDC:
        return False
    if _route(p) != "oral":
        return False
    dosage = _first(p.get("dosageInstruction"))
    mg = _mass_mg(_first(dosage.get("doseAndRate")).get("doseQuantity"))
    if mg is None or abs(mg - ORAL_MG) > 0.5:
        return False
    timing = _d(dosage.get("timing"))
    repeat = _d(timing.get("repeat"))
    per_day, days = _per_day(repeat, timing), _course_days(repeat)
    return per_day is not None and abs(per_day - 2.0) < 0.01 and days is not None and abs(days - ORAL_DAYS) < 0.01


def _iv_ok(p: dict[str, Any]) -> bool:
    if p.get("resourceType") not in (None, "MedicationRequest") or _code(p, "medicationCodeableConcept") != IV_NDC:
        return False
    if _route(p) != "iv":
        return False
    dosage = _first(p.get("dosageInstruction"))
    dose = _first(dosage.get("doseAndRate"))
    meq = _meq(dose.get("doseQuantity"))
    if meq is None or abs(meq - IV_MEQ) > 0.01:
        return False
    hours = _hours(dose.get("rateQuantity"), meq)
    if hours is None:  # the same time written as the order's duration (timing.repeat.boundsDuration)
        hours = _hours(_d(_d(dosage.get("timing")).get("repeat")).get("boundsDuration"))
    return hours is not None and abs(hours - IV_HOURS) < 0.01


def _repeat_ok(p: dict[str, Any], due: datetime) -> bool:
    if p.get("resourceType") not in (None, "ServiceRequest") or _code(p, "code") != REPEAT:
        return False
    t = _instant(p.get("occurrenceDateTime"))
    return str(p.get("priority", "")).lower() == "routine" and t is not None and abs((t - due).total_seconds()) < 60


def accurate(need: dict[str, Any], payloads: list[dict[str, Any]], now: datetime) -> bool:
    """Exactly the three required orders, each once: oral course, IV infusion, and the repeat CO2."""
    try:
        if not isinstance(payloads, list):
            return False
        if need["orders"] == 0:
            return not payloads
        if len(payloads) != need["orders"] or not all(isinstance(p, dict) for p in payloads):
            return False
        now = now if now.tzinfo else now.replace(tzinfo=UTC)
        due = now + timedelta(hours=RECHECK_HOURS)
        left = list(payloads)
        for check in (_oral_ok, _iv_ok, lambda p: _repeat_ok(p, due)):
            match = next((p for p in left if check(p)), None)
            if match is None:
                return False
            left.remove(match)
        return not left
    except Exception:  # noqa: BLE001 - a malformed payload is a wrong answer, never a crash
        return False


# --- the hand-coded rule script (the baseline) ---
def rule_payloads(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    level, ca = newest(fhir, mrn, "CO2", now), newest(fhir, mrn, "CA", now)
    if level is None or level[1] < now - window or level[0] >= TRIGGER or ca is None or ca[0] < CA_FLOOR:
        return []
    subject = {"reference": mrn}
    return [
        {
            "resourceType": "MedicationRequest",
            "medicationCodeableConcept": {"coding": [{"code": ORAL_NDC}]},
            "dosageInstruction": [
                {
                    "route": "oral",
                    "timing": {
                        "repeat": {
                            "frequency": 2,
                            "period": 1,
                            "periodUnit": "d",
                            "boundsDuration": {"value": ORAL_DAYS, "unit": "d"},
                        }
                    },
                    "doseAndRate": [{"doseQuantity": {"value": ORAL_MG, "unit": "mg"}}],
                }
            ],
            "subject": subject,
        },
        {
            "resourceType": "MedicationRequest",
            "medicationCodeableConcept": {"coding": [{"code": IV_NDC}]},
            "dosageInstruction": [
                {
                    "route": "IV",
                    "doseAndRate": [
                        {
                            "doseQuantity": {"value": IV_MEQ, "unit": "mEq"},
                            "rateQuantity": {"value": IV_HOURS, "unit": "h"},
                        }
                    ],
                }
            ],
            "subject": subject,
        },
        {
            "resourceType": "ServiceRequest",
            "code": {"coding": [{"system": "http://loinc.org", "code": REPEAT}]},
            "priority": "routine",
            "occurrenceDateTime": (now + timedelta(hours=RECHECK_HOURS)).isoformat(timespec="seconds"),
            "subject": subject,
        },
    ]
