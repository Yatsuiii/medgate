"""High INR protocol: tiered oral or IV vitamin K, a repeat INR at a relative time, and a platelet exclusion.

Oracle (needs), judge (accurate) and hand-coded rule script (rule_payloads) for this protocol. Analysis code only.
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from heldout import newest  # noqa: E402

from medgate.fhir import FhirClient  # noqa: E402
from medgate.protocol import FHIR_BASE  # noqa: E402
from medgate.results import clinical_time  # noqa: E402

PROTOCOL = {
    "name": "High INR reversal",
    "code": "INR",
    "text": (
        "High INR protocol (INR, code INR, drawn in the last 24 hours). If the newest INR is 1.4 or higher, order "
        "vitamin K (phytonadione) by level: 1.4 to below 1.8, oral tablet, NDC 57664-0254-88, route oral, 1 mg as a "
        "single dose; 1.8 to below 2.0, oral tablet, NDC 57664-0254-88, route oral, 2.5 mg as a single dose; 2.0 or "
        "higher, IV injection, NDC 0517-0451-25, route IV, 5 mg over 30 minutes. Record the dose in mg; for the IV "
        "order record the duration as a rate in hours. Pair that order with a repeat INR, LOINC 6301-6, priority "
        "routine, to be drawn 24 hours after the order is written for the oral doses and 6 hours after the order is "
        "written for the IV dose. If the INR is below 1.4, order nothing. Exclusion: before ordering, check the "
        "newest platelet count (code PLT). If it is below 50 x10^3/uL, do not order vitamin K; hold it for physician "
        "review."
    ),
}
LOW = 1.4
PLATELET_FLOOR = 50.0


def _inr(fhir: FhirClient, mrn: str, now: datetime) -> tuple[float, datetime, str] | None:
    """The newest INR on or before `now` as (value, time, observation id), or None."""
    url = f"{FHIR_BASE}Observation?patient={mrn}&code=INR&_count=5000&_format=json"
    found = []
    for entry in json.loads(str(fhir.get(url).data)).get("entry", []):
        r = entry["resource"]
        t = clinical_time(r)
        v = (r.get("valueQuantity") or {}).get("value")
        if t is not None and t <= now and v is not None:
            found.append((t, float(v), str(r["id"])))
    if not found:
        return None
    t, v, i = max(found)
    return v, t, i


def _tier(inr: float) -> tuple[float, str, int]:
    """(mg, route, hours until the repeat INR) for an INR of 1.4 or higher."""
    return (1.0, "oral", 24) if inr < 1.8 else (2.5, "oral", 24) if inr < 2.0 else (5.0, "iv", 6)


def needs(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    """What the text requires for this patient, or None if there is no fresh INR or no platelet count to check."""
    inr = _inr(fhir, mrn, now)
    if inr is None or inr[1] < now - window:
        return None
    value, _, obs = inr
    if value < LOW:
        return {"orders": 0, "held": False, "value": value, "obs": obs}
    plt = newest(fhir, mrn, "PLT", now)
    if plt is None:
        return None
    if plt[0] < PLATELET_FLOOR:
        return {"orders": 0, "held": True, "value": value, "obs": obs, "platelets": plt[0]}
    mg, route, hours = _tier(value)
    return {"orders": 2, "held": False, "value": value, "obs": obs, "mg": mg, "route": route, "hours": hours}


# --- the judge ---
def _d(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _first(x: Any) -> dict[str, Any]:
    return _d(x[0]) if isinstance(x, list) and x else {}


def _code(p: dict[str, Any], field: str) -> str:
    return str(_first(_d(p.get(field)).get("coding")).get("code", "")).strip()


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, int | float) and not isinstance(x, bool) else None


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


def _mg(q: Any) -> float | None:
    q = _d(q)
    v, unit = _num(q.get("value")), str(q.get("unit") or q.get("code") or "").strip().lower()
    scale = {"mg": 1.0, "g": 1000.0, "mcg": 0.001, "ug": 0.001}.get(unit)
    return None if v is None or scale is None else v * scale


def _hours_of_infusion(rate: Any, mg: float) -> float | None:
    """The infusion time in hours implied by a rateQuantity, whether given as a duration or as a dose rate."""
    q = _d(rate)
    v, unit = _num(q.get("value")), str(q.get("unit") or q.get("code") or "").strip().lower().replace(" ", "")
    if v is None or v <= 0:
        return None
    if unit in ("h", "hr", "hrs", "hour", "hours"):
        return v
    if unit in ("min", "mins", "minute", "minutes"):
        return v / 60
    per = {"mg/h": 1.0, "mg/hr": 1.0, "mg/min": 60.0, "g/h": 1000.0, "g/hr": 1000.0}.get(unit)
    return None if per is None else mg / (v * per)


def _instant(x: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except ValueError:
        return None
    if "T" not in str(x):
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _medication_ok(p: dict[str, Any], mg: float, route: str) -> bool:
    ndc = "0517-0451-25" if route == "iv" else "57664-0254-88"
    if p.get("resourceType") not in (None, "MedicationRequest") or _code(p, "medicationCodeableConcept") != ndc:
        return False
    if _route(p) != route:
        return False
    dose = _first(_first(p.get("dosageInstruction")).get("doseAndRate"))
    given = _mg(dose.get("doseQuantity"))
    if given is None or abs(given - mg) > 0.01:
        return False
    if route == "oral":
        return True
    hours = _hours_of_infusion(dose.get("rateQuantity"), mg)
    if hours is None:  # the same course length written as the order's duration (timing.repeat.boundsDuration)
        bounds = _d(_d(_d(_first(p.get("dosageInstruction")).get("timing")).get("repeat")).get("boundsDuration"))
        hours = _hours_of_infusion(bounds, mg)
    return hours is not None and abs(hours - 0.5) < 0.01


def _repeat_ok(p: dict[str, Any], due: datetime) -> bool:
    if p.get("resourceType") not in (None, "ServiceRequest") or _code(p, "code") != "6301-6":
        return False
    t = _instant(p.get("occurrenceDateTime"))
    return str(p.get("priority", "")).lower() == "routine" and t is not None and abs((t - due).total_seconds()) < 60


def accurate(need: dict[str, Any], payloads: list[dict[str, Any]], now: datetime) -> bool:
    """Exactly the required orders: the vitamin K at this level's dose, route and duration, and the repeat INR."""
    try:
        if not isinstance(payloads, list):
            return False
        if need["orders"] == 0:
            return not payloads
        if len(payloads) != need["orders"] or not all(isinstance(p, dict) for p in payloads):
            return False
        now = now if now.tzinfo else now.replace(tzinfo=UTC)
        due = now + timedelta(hours=need["hours"])
        return any(_medication_ok(p, need["mg"], need["route"]) for p in payloads) and any(
            _repeat_ok(p, due) for p in payloads
        )
    except Exception:  # noqa: BLE001 - a malformed payload is a wrong answer, never a crash
        return False


# --- the hand-coded rule script (the baseline) ---
def rule_payloads(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    inr, plt = _inr(fhir, mrn, now), newest(fhir, mrn, "PLT", now)
    if inr is None or inr[1] < now - window or inr[0] < 1.4 or plt is None or plt[0] < 50:
        return []
    mg, route, hours = _tier(inr[0])
    ref, subject = [{"reference": f"Observation/{inr[2]}"}], {"reference": mrn}
    dose = {"doseQuantity": {"value": mg, "unit": "mg"}}
    if route == "iv":
        dose["rateQuantity"] = {"value": 0.5, "unit": "h"}
    return [
        {
            "medicationCodeableConcept": {"coding": [{"code": "0517-0451-25" if route == "iv" else "57664-0254-88"}]},
            "dosageInstruction": [{"route": route.upper() if route == "iv" else "oral", "doseAndRate": [dose]}],
            "subject": subject,
            "reasonReference": ref,
        },
        {
            "code": {"coding": [{"code": "6301-6"}]},
            "priority": "routine",
            "occurrenceDateTime": (now + timedelta(hours=hours)).isoformat(timespec="seconds"),
            "subject": subject,
            "reasonReference": ref,
        },
    ]
