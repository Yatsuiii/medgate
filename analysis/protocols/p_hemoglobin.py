"""Hemoglobin drop protocol: type and screen plus a repeat HGB, both ServiceRequests. Oracle, judge and rule script."""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from heldout_run import _code  # noqa: E402

from medgate.protocol import FHIR_BASE  # noqa: E402
from medgate.results import clinical_time  # noqa: E402

PROTOCOL = {
    "name": "Hemoglobin drop",
    "code": "HGB",
    "text": (
        "Hemoglobin drop protocol (hemoglobin, code HGB, drawn in the last 24 hours). Compare the newest hemoglobin "
        "with the previous hemoglobin, meaning the next older HGB result, but only if it was drawn within 48 hours "
        "before the newest; if there is no such previous result, order nothing. If the newest hemoglobin is at least "
        "1.0 g/dL lower than the previous one, order two lab orders, each a ServiceRequest. First, a type and screen, "
        "LOINC 882-1: priority stat if the drop is 2.0 g/dL or more, priority routine if the drop is 1.0 g/dL to "
        "below 2.0 g/dL. Second, a repeat hemoglobin, LOINC 718-7, priority routine, to be drawn at 08:00 on the "
        "calendar day after the order is written, in the time zone of the current time. If the drop is below 1.0 "
        "g/dL, or the hemoglobin rose or stayed the same, order nothing. Exclusion: if the newest hemoglobin is below "
        "7.0 g/dL, do not order; hold it for physician review of transfusion."
    ),
}


def series(fhir: Any, mrn: str, now: datetime) -> list[tuple[datetime, float]]:
    """HGB results on or before now, newest first."""
    url = f"{FHIR_BASE}Observation?patient={mrn}&code=HGB&_count=5000&_format=json"
    found = []
    for e in json.loads(str(fhir.get(url).data)).get("entry", []):
        r = e["resource"]
        t, v = clinical_time(r), (r.get("valueQuantity") or {}).get("value")
        if t is not None and t <= now and v is not None:
            found.append((t, float(v)))
    return sorted(found, reverse=True)


def needs(fhir: Any, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    """The oracle. None if no fresh HGB or no usable previous one (missing, or tied times with unequal values)."""
    rows = series(fhir, mrn, now)
    if not rows or rows[0][0] < now - window:
        return None
    t0 = rows[0][0]
    newest = {v for t, v in rows if t == t0}
    older = [(t, v) for t, v in rows if t < t0]
    if len(newest) != 1 or not older or older[0][0] < t0 - timedelta(hours=48):
        return None
    prev = {v for t, v in older if t == older[0][0]}
    if len(prev) != 1:
        return None
    value, previous = newest.pop(), prev.pop()
    drop = round(previous - value, 1)
    act = drop >= 1.0
    held = act and value < 7.0
    due = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    return {
        "orders": 2 if act and not held else 0,
        "held": held,
        "value": value,
        "previous": previous,
        "drop": drop,
        "ts_priority": "stat" if drop >= 2.0 else "routine",
        "due": due.isoformat(),
    }


def _instant(text: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _request(p: Any, loinc: str, priority: str) -> dict[str, Any] | None:
    if not isinstance(p, dict) or p.get("resourceType", "ServiceRequest") != "ServiceRequest":
        return None
    right = _code(p, "code") == loinc and str(p.get("priority", "")).lower() == priority
    return p if right else None


def accurate(need: dict[str, Any], payloads: list[Any], now: datetime) -> bool:
    """The judge: a type and screen at the right priority and a repeat HGB, routine, at 08:00 next day."""
    try:
        if need.get("orders") != 2:  # nothing to order, or held for physician review: any order is wrong
            return not payloads
        if len(payloads) != 2:  # exactly the two protocol orders: no extra, duplicate or unrelated order
            return False
        due = _instant(need["due"])
        screens = [p for p in payloads if _request(p, "882-1", need["ts_priority"])]
        repeats = [
            p
            for p in payloads
            if (r := _request(p, "718-7", "routine")) is not None and _instant(r.get("occurrenceDateTime")) == due
        ]
        return len(screens) == 1 and len(repeats) == 1
    except Exception:  # noqa: BLE001 - a malformed payload is a wrong answer, never a crash
        return False


def rule_payloads(fhir: Any, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    """The coded order set, written on its own from the protocol text."""
    rows = sorted(set(series(fhir, mrn, now)), reverse=True)  # repeated identical results count once
    if len(rows) < 2 or rows[0][0] < now - window or rows[1][0] < rows[0][0] - timedelta(hours=48):
        return []
    drop = round(rows[1][1] - rows[0][1], 1)
    if drop < 1.0 or rows[0][1] < 7.0:
        return []
    due = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0).isoformat()
    ts, rep = {"resourceType": "ServiceRequest", "subject": {"reference": mrn}}, {"resourceType": "ServiceRequest"}
    ts.update(code={"coding": [{"code": "882-1"}]}, priority="stat" if drop >= 2.0 else "routine")
    rep.update(code={"coding": [{"code": "718-7"}]}, priority="routine", occurrenceDateTime=due, subject=ts["subject"])
    return [ts, rep]
