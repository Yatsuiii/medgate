"""Rising-creatinine protocol (trend rule): oracle, judge and hand-coded rule script. Analysis code, never the product.

Import this module from analysis scripts after putting the repository's `analysis/` directory on sys.path. Nothing here
touches the network until `needs` or `rule_payloads` is called with a FHIR client.
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from heldout_run import _code  # noqa: E402

from medgate.protocol import FHIR_BASE  # noqa: E402
from medgate.results import clinical_time  # noqa: E402

PROTOCOL = {
    "name": "Rising creatinine",
    "code": "CR",
    "text": (
        "Rising creatinine protocol (serum creatinine, code CR, in mg/dL). Compare the newest creatinine with the "
        "previous creatinine, meaning the next older creatinine result in the record, if it was drawn no more than 48 "
        "hours before the newest one. If the newest creatinine is at least 0.2 mg/dL higher than that previous "
        "creatinine, place two orders, both as service requests with the creatinine result cited. First, a repeat "
        "serum creatinine, LOINC 2160-0, priority routine, to be drawn at 06:00 UTC on the calendar day after the "
        "order is written. Second, a medication review for kidney-risk drugs, SNOMED 182836005, priority urgent, to be "
        "performed 4 hours after the order is written; if the rise is 0.5 mg/dL or more, make that review priority "
        "stat instead of urgent. If the newest creatinine is less than 0.2 mg/dL higher than the previous one, or is "
        "lower or unchanged, order nothing. Exclusion: if there is no previous creatinine drawn within 48 hours before "
        "the newest one, do not order; hold it for pharmacist review."
    ),
}
REPEAT, REVIEW = "2160-0", "182836005"


def needs(fhir: Any, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    """What the text requires for this patient, or None if there is no fresh CR or the text cannot be applied."""
    found = json.loads(str(fhir.get(f"{FHIR_BASE}Observation?patient={mrn}&code=CR&_count=5000&_format=json").data))
    timed = [(t, r) for e in found.get("entry", []) if (t := clinical_time(r := e["resource"])) and t <= now]
    if not timed:
        return None
    time = max(t for t, _ in timed)
    top = [r for t, r in timed if t == time]
    if time < now - window or len(top) != 1:
        return None
    valued = [(t, r["valueQuantity"]) for t, r in timed if isinstance(r.get("valueQuantity"), dict)]
    value = dict(valued).get(time) if top[0].get("valueQuantity") else None
    if value is None or value.get("unit") != "mg/dL" or value.get("value") is None:
        return None
    older = [(t, q) for t, q in valued if t < time]
    base = {"value": float(value["value"]), "obs": top[0]["id"], "time": time.isoformat()}
    if not older or time - max(t for t, _ in older) > timedelta(hours=48):
        return {**base, "orders": 0, "held": True}
    prev_time = max(t for t, _ in older)
    previous = {q.get("value") for t, q in older if t == prev_time}
    if len(previous) != 1 or None in previous:
        return None  # two different results at the previous time: which is "the previous creatinine" is ambiguous
    delta = round(base["value"] - float(previous.pop()), 2)
    rise = delta >= 0.2
    return {**base, "orders": 2 if rise else 0, "held": False, "delta": delta, "stat": delta >= 0.5}


def _when(payload: dict[str, Any]) -> datetime | None:
    raw = payload.get("occurrenceDateTime") or (
        payload["occurrencePeriod"].get("start") if isinstance(payload.get("occurrencePeriod"), dict) else None
    )
    if not isinstance(raw, str) or "T" not in raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _matches(p: Any, code: str, priority: str, due: datetime) -> bool:
    if not isinstance(p, dict) or p.get("resourceType", "ServiceRequest") != "ServiceRequest":
        return False
    when = _when(p)
    return (
        _code(p, "code") == code
        and str(p.get("priority", "")).lower() == priority
        and when is not None
        and abs(when - due) <= timedelta(minutes=1)
    )


def accurate(need: dict[str, Any], payloads: list[dict[str, Any]], now: datetime) -> bool:
    """Exactly the repeat creatinine and the medication review (right code, priority, time), and nothing else."""
    try:
        if int(need["orders"]) != 2 or len(payloads) != 2:
            return False
        now = now if now.tzinfo else now.replace(tzinfo=UTC)
        tomorrow = (now.astimezone(UTC) + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
        review_priority = "stat" if need.get("stat") else "urgent"
        return any(_matches(p, REPEAT, "routine", tomorrow) for p in payloads) and any(
            _matches(p, REVIEW, review_priority, now + timedelta(hours=4)) for p in payloads
        )
    except Exception:
        return False


def rule_payloads(fhir: Any, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    need = needs(fhir, mrn, now, window)
    if not need or not need["orders"]:
        return []
    tomorrow = (now.astimezone(UTC) + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
    base = {"resourceType": "ServiceRequest", "subject": {"reference": mrn}}
    base["reasonReference"] = [{"reference": f"Observation/{need['obs']}"}]
    return [
        {
            **base,
            "code": {"coding": [{"code": REPEAT}]},
            "priority": "routine",
            "occurrenceDateTime": tomorrow.isoformat(),
        },
        {
            **base,
            "code": {"coding": [{"code": REVIEW}]},
            "priority": "stat" if need["stat"] else "urgent",
            "occurrenceDateTime": (now + timedelta(hours=4)).isoformat(),
        },
    ]
