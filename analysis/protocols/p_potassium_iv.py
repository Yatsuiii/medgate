"""High-risk low potassium protocol: oral or IV potassium chloride by level, a paired recheck at a tier-specific time.

Exclusion: newest creatinine above a stated threshold holds the order. Oracle (needs), judge (accurate) and
hand-coded rule script (rule_payloads). Analysis code only.

Data note: only 3 patients have K below 3.5 in the 24 h window, so the tiers are moved up: IV below 3.6, oral 3.6
to below 3.8. The IV NDC is not used elsewhere in the repo (no IV potassium exists in the benchmark data).
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

ORAL_NDC, IV_NDC = "40032-917-01", "0409-6652-23"
IV_BELOW, ORAL_BELOW, CR_LIMIT = 3.6, 3.8, 1.5

PROTOCOL = {
    "name": "High-risk low potassium",
    "code": "K",
    "text": (
        "High-risk low potassium protocol (serum potassium, code K, drawn in the last 24 hours). Order potassium "
        "chloride by the newest potassium: below 3.6 mmol/L, IV potassium chloride, NDC 0409-6652-23, route IV, "
        "20 mEq over 4 hours; 3.6 to below 3.8 mmol/L, oral potassium chloride, NDC 40032-917-01, route oral, "
        "20 mEq as a single dose. Record the dose in mEq; for the IV order record the duration as a rate in hours. "
        "Pair that order with a repeat serum potassium, LOINC 2823-3, priority routine, to be drawn 6 hours after "
        "the order is written for the IV dose and 24 hours after the order is written for the oral dose. If the "
        "potassium is 3.8 or higher, order nothing. Exclusion: before ordering, check the newest creatinine (code "
        "CR). If it is above 1.5 mg/dL, do not order potassium; hold it for physician review."
    ),
}


def _tier(k: float) -> tuple[str, int]:
    """(route, hours until the recheck) for a potassium below 3.8."""
    return ("iv", 6) if k < IV_BELOW else ("oral", 24)


def _k(fhir: FhirClient, mrn: str, now: datetime) -> tuple[float, datetime, str] | None:
    url = f"{FHIR_BASE}Observation?patient={mrn}&code=K&_count=5000&_format=json"
    found = []
    for entry in json.loads(str(fhir.get(url).data)).get("entry", []):
        r = entry["resource"]
        t, v = clinical_time(r), (r.get("valueQuantity") or {}).get("value")
        if t is not None and t <= now and v is not None:
            found.append((t, float(v), str(r["id"])))
    if not found:
        return None
    t, v, i = max(found)
    return v, t, i


def needs(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    """What the text requires, or None if there is no fresh potassium or no creatinine to check."""
    k = _k(fhir, mrn, now)
    if k is None or k[1] < now - window:
        return None
    value, _, obs = k
    if value >= ORAL_BELOW:
        return {"orders": 0, "held": False, "value": value, "obs": obs}
    cr = newest(fhir, mrn, "CR", now)
    if cr is None:
        return None
    if cr[0] > CR_LIMIT:
        return {"orders": 0, "held": True, "value": value, "obs": obs, "creatinine": cr[0]}
    route, hours = _tier(value)
    return {"orders": 2, "held": False, "value": value, "obs": obs, "route": route, "hours": hours, "meq": 20.0}


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
    coding = _first(r.get("coding"))
    text = r.get("text") or coding.get("display") or coding.get("code") or route
    text = str(text if isinstance(text, str) else "").strip().lower()
    return (
        "iv"
        if text in ("iv", "intravenous", "iv infusion", "iv piggyback", "47625008")
        else "oral"
        if text in ("oral", "po", "by mouth", "26643006")
        else text
    )


def _meq(q: Any) -> float | None:
    q = _d(q)
    v, unit = _num(q.get("value")), str(q.get("unit") or q.get("code") or "").strip().lower()
    return v if v is not None and unit in ("meq", "mmol") else None  # K+ is monovalent: 1 mEq = 1 mmol


def _hours(rate: Any, meq: float) -> float | None:
    q = _d(rate)
    v, unit = _num(q.get("value")), str(q.get("unit") or q.get("code") or "").strip().lower().replace(" ", "")
    if v is None or v <= 0:
        return None
    if unit in ("h", "hr", "hrs", "hour", "hours"):
        return v
    if unit in ("min", "mins", "minute", "minutes"):
        return v / 60
    per = {"meq/h": 1.0, "meq/hr": 1.0, "mmol/h": 1.0, "meq/min": 60.0}.get(unit)
    return None if per is None else meq / (v * per)


def _instant(x: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except ValueError:
        return None
    if "T" not in str(x):
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _medication_ok(p: dict[str, Any], need: dict[str, Any]) -> bool:
    route = need["route"]
    if p.get("resourceType") not in (None, "MedicationRequest"):
        return False
    if _code(p, "medicationCodeableConcept") != (IV_NDC if route == "iv" else ORAL_NDC) or _route(p) != route:
        return False
    dose = _first(_first(p.get("dosageInstruction")).get("doseAndRate"))
    given = _meq(dose.get("doseQuantity"))
    if given is None or abs(given - need["meq"]) > 0.01:
        return False
    if route == "oral":
        return True
    hours = _hours(dose.get("rateQuantity"), need["meq"])
    if hours is None:
        bounds = _d(_d(_d(_first(p.get("dosageInstruction")).get("timing")).get("repeat")).get("boundsDuration"))
        hours = _hours(bounds, need["meq"])
    return hours is not None and abs(hours - 4.0) < 0.01


def _recheck_ok(p: dict[str, Any], due: datetime) -> bool:
    if p.get("resourceType") not in (None, "ServiceRequest") or _code(p, "code") != "2823-3":
        return False
    t = _instant(p.get("occurrenceDateTime"))
    return str(p.get("priority", "")).lower() == "routine" and t is not None and abs((t - due).total_seconds()) < 60


def accurate(need: dict[str, Any], payloads: list[dict[str, Any]], now: datetime) -> bool:
    """Exactly the required orders: this tier's potassium chloride order and the recheck at its time."""
    try:
        if not isinstance(payloads, list):
            return False
        if need["orders"] == 0:
            return not payloads
        if len(payloads) != need["orders"] or not all(isinstance(p, dict) for p in payloads):
            return False
        now = now if now.tzinfo else now.replace(tzinfo=UTC)
        due = now + timedelta(hours=need["hours"])
        return any(_medication_ok(p, need) for p in payloads) and any(_recheck_ok(p, due) for p in payloads)
    except Exception:  # noqa: BLE001 - a malformed payload is a wrong answer, never a crash
        return False


# --- the hand-coded rule script ---
def rule_payloads(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    k, cr = _k(fhir, mrn, now), newest(fhir, mrn, "CR", now)
    if k is None or k[1] < now - window or k[0] >= ORAL_BELOW or cr is None or cr[0] > CR_LIMIT:
        return []
    route, hours = _tier(k[0])
    ref, subject = [{"reference": f"Observation/{k[2]}"}], {"reference": mrn}
    dose: dict[str, Any] = {"doseQuantity": {"value": 20, "unit": "mEq"}}
    if route == "iv":
        dose["rateQuantity"] = {"value": 4, "unit": "h"}
    return [
        {
            "medicationCodeableConcept": {"coding": [{"code": IV_NDC if route == "iv" else ORAL_NDC}]},
            "dosageInstruction": [{"route": "IV" if route == "iv" else "oral", "doseAndRate": [dose]}],
            "subject": subject,
            "reasonReference": ref,
        },
        {
            "code": {"coding": [{"code": "2823-3"}]},
            "priority": "routine",
            "occurrenceDateTime": (now + timedelta(hours=hours)).isoformat(timespec="seconds"),
            "subject": subject,
            "reasonReference": ref,
        },
    ]
