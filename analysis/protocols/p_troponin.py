"""High-sensitivity troponin protocol: oracle, judge and rule script. Analysis code only, never shown to the agent."""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from heldout_run import _dict  # noqa: E402

from medgate.fhir import FhirClient  # noqa: E402
from medgate.protocol import FHIR_BASE  # noqa: E402
from medgate.results import clinical_time  # noqa: E402

CUTOFF = 8.0  # ng/L
CK_HOLD = 1000.0  # U/L
REPEAT_HOURS = 3
TROPONIN_LOINC, ECG_LOINC = "89579-7", "11524-6"

PROTOCOL = {
    "name": "High-sensitivity troponin",
    "code": "HISENSTNI",
    "text": (
        "High-sensitivity troponin protocol (troponin I, code HISENSTNI, drawn in the last 24 hours). If the newest "
        "troponin is above 8 ng/L, place two orders, both as ServiceRequest with no medication: a repeat "
        "high-sensitivity troponin I, LOINC 89579-7, priority routine, to be drawn 3 hours after the order is "
        "written, and a 12-lead ECG, LOINC 11524-6, priority stat, to be performed at the time the order is "
        "written. If the troponin is 8 ng/L or below, order nothing. Exclusion: before ordering, check for a "
        "creatine kinase (code CK) drawn in the last 24 hours; if the newest such CK is above 1000 U/L, the "
        "troponin may reflect muscle injury: do not order, hold it for physician review. If there is no CK in "
        "the last 24 hours, the exclusion does not apply."
    ),
}


def _latest(fhir: FhirClient, mrn: str, code: str, now: datetime, window: timedelta) -> tuple[float, str] | None:
    """(value, observation id) of the newest result of `code` on or before `now` and inside the window, or None."""
    url = f"{FHIR_BASE}Observation?patient={mrn}&code={code}&_count=5000&_format=json"
    found = []
    for entry in json.loads(str(fhir.get(url).data)).get("entry", []):
        r = entry["resource"]
        t, v = clinical_time(r), (r.get("valueQuantity") or {}).get("value")
        if t is not None and now - window <= t <= now and v is not None:
            found.append((t, float(v), str(r["id"])))
    if not found:
        return None
    _, value, obs = max(found)
    return value, obs


def needs(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    """The protocol applied as written. None when there is no troponin in the window."""
    tn = _latest(fhir, mrn, "HISENSTNI", now, window)
    if tn is None:
        return None
    ck = _latest(fhir, mrn, "CK", now, window)
    high = tn[0] > CUTOFF
    held = high and ck is not None and ck[0] > CK_HOLD
    return {"orders": 2 if high and not held else 0, "held": held, "value": tn[0], "obs": tn[1]}


def _when(payload: dict[str, Any]) -> datetime | None:
    raw = payload.get("occurrenceDateTime") or _dict(payload.get("occurrencePeriod")).get("start")
    try:
        t = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _order_ok(p: Any, loinc: str, priority: str, due: datetime) -> bool:
    if not isinstance(p, dict) or p.get("resourceType", "ServiceRequest") != "ServiceRequest":
        return False
    when = _when(p)
    return (
        loinc in {str(c.get("code")) for c in _dict(p.get("code")).get("coding") or [] if isinstance(c, dict)}
        and str(p.get("priority", "")).lower() == priority
        and when is not None
        and abs((when - due).total_seconds()) < 60
        and not any(k in p for k in ("medicationCodeableConcept", "medicationReference", "dosageInstruction"))
    )


def accurate(need: dict[str, Any], payloads: list[Any], now: datetime) -> bool:
    """Exactly the repeat troponin (3 h after now, routine) and the ECG (now, stat), and nothing else."""
    try:
        if int(need["orders"]) == 0:
            return payloads == []  # a hold or a normal troponin: ordering nothing is the correct answer
        if int(need["orders"]) != 2 or len(payloads) != 2:
            return False
        repeat = any(_order_ok(p, TROPONIN_LOINC, "routine", now + timedelta(hours=REPEAT_HOURS)) for p in payloads)
        ecg = any(_order_ok(p, ECG_LOINC, "stat", now) for p in payloads)
        return repeat and ecg
    except Exception:
        return False


def rule_payloads(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    need = needs(fhir, mrn, now, window)
    if need is None or need["orders"] == 0:
        return []
    base = {"subject": {"reference": mrn}, "reasonReference": [{"reference": f"Observation/{need['obs']}"}]}
    return [
        {
            **base,
            "code": {"coding": [{"code": TROPONIN_LOINC}]},
            "priority": "routine",
            "occurrenceDateTime": (now + timedelta(hours=REPEAT_HOURS)).isoformat(timespec="seconds"),
        },
        {
            **base,
            "code": {"coding": [{"code": ECG_LOINC}]},
            "priority": "stat",
            "occurrenceDateTime": now.isoformat(timespec="seconds"),
        },
    ]
