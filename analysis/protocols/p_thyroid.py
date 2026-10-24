"""Two-sided reflex-order protocol (sodium screen). Oracle, judge and rule script live here, never in the product.

The assigned shape was thyroid screening (TSH), but only 2 patients have a TSH in the 24-hour window, so the data
cannot support it. This is the same shape on sodium (NA, 94 fresh results): one reflex lab when the value is above a
high limit or below a low limit, nothing in between, no medication.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from heldout import newest  # noqa: E402

LOW, HIGH, GLUCOSE_LIMIT, HOURS = 133.0, 145.0, 250.0, 2

PROTOCOL = {
    "name": "Sodium screen",
    "code": "NA",
    "text": (
        "Sodium screening protocol (serum sodium, code NA, drawn in the last 24 hours). If the newest sodium is below "
        "133 mmol/L or above 145 mmol/L, order one serum osmolality, LOINC 2692-2, priority routine, to be drawn "
        f"{HOURS} hours after the order is written. This is the only order; no medication is ordered. If the sodium is "
        "133 to 145 mmol/L inclusive, order nothing. Exclusion: before ordering for a low sodium, check the newest "
        "glucose (code GLU). If it is above 250 mg/dL, the low sodium may reflect hyperglycemia: do not order, hold it "
        "for pharmacist review."
    ),
}


def needs(fhir: Any, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    """The oracle: what the text requires for this patient, or None if there is no fresh sodium or no glucose."""
    na = newest(fhir, mrn, "NA", now)
    if na is None or na[1] < now - window:
        return None
    value, low = na[0], na[0] < LOW
    if not low and value <= HIGH:
        return {"orders": 0, "held": False, "value": value}
    glucose = newest(fhir, mrn, "GLU", now) if low else None
    if low and glucose is None:
        return None  # the exclusion cannot be applied
    held = low and glucose is not None and glucose[0] > GLUCOSE_LIMIT
    return {"orders": 0 if held else 1, "held": held, "value": value}


def _dict(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _instant(text: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _loinc_codes(p: dict[str, Any]) -> set[str]:
    """Codes in the order's coding list; a coding naming a non-LOINC system does not count as a LOINC code."""
    coding = _dict(p.get("code")).get("coding")
    codes: set[str] = set()
    for c in coding if isinstance(coding, list) else []:
        c = _dict(c)
        system, code = c.get("system"), c.get("code")
        if isinstance(code, str) and (system is None or "loinc" in str(system).lower()):
            codes.add(code.strip())
    return codes


def accurate(need: dict[str, Any], payloads: list[Any], now: datetime) -> bool:
    """True iff the payloads are exactly the required orders: for a need of orders=1, a single serum osmolality
    order, routine, drawn HOURS after `now`, and nothing else (no extra, duplicate or medication order)."""
    if int(_dict(need).get("orders", 1)) == 0:
        return not payloads
    if not isinstance(payloads, list) or len(payloads) != 1:
        return False
    p = _dict(payloads[0])
    when = _instant(p.get("occurrenceDateTime"))
    due = now + timedelta(hours=HOURS)
    return (
        p.get("resourceType", "ServiceRequest") == "ServiceRequest"
        and "2692-2" in _loinc_codes(p)
        and str(p.get("priority", "")).lower() == "routine"
        and when is not None
        and abs((when - due).total_seconds()) < 60
    )


def rule_payloads(fhir: Any, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    need = needs(fhir, mrn, now, window)
    if not need or not need["orders"]:
        return []
    return [
        {
            "resourceType": "ServiceRequest",
            "code": {"coding": [{"code": "2692-2"}]},
            "priority": "routine",
            "occurrenceDateTime": (now + timedelta(hours=HOURS)).isoformat(timespec="seconds"),
            "subject": {"reference": mrn},
        }
    ]
