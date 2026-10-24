"""White cell count follow-up: only ServiceRequest lab orders (no medication), a stat and a timed routine order, a third
order for the severe tier only, and a platelet hold.

Oracle (needs), judge (accurate) and hand-coded rule script (rule_payloads) for this protocol. Analysis code only.
Data adaptation: thresholds are set so six of the twelve patients with a WBC in the 24 hour window need orders
(10.2, 10.8, 10.9, 4.2 standard; 19.0, 2.3 severe) and one (12.7, platelets 75) is held.
The benchmark has no LOINC for these orders; the four codes below are real LOINC codes stated by the text only.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from heldout import newest  # noqa: E402

from medgate.fhir import FhirClient  # noqa: E402

CBC, WBC_REPEAT, CULTURE = "57021-8", "6690-2", "600-7"
PLT_FLOOR = 100.0
RECHECK_HOURS = 12

PROTOCOL = {
    "name": "Abnormal white cell count follow-up",
    "code": "WBC",
    "text": (
        "White cell count follow-up protocol (WBC, code WBC, drawn in the last 24 hours). This protocol orders "
        "laboratory tests only, never medication. If the newest WBC is above 10.0 or below 4.5 (x10^3/uL), place two "
        "lab orders: a CBC with automated differential, LOINC 57021-8, priority stat, to be drawn now (the time the "
        "orders are written); and a repeat WBC count, LOINC 6690-2, priority routine, to be drawn 12 hours after the "
        "orders are written. If the newest WBC is above 15.0 or below 3.0, also place a third order: blood culture, "
        "LOINC 600-7, priority urgent, to be drawn now; this third order is for that severe tier only. Give each "
        "order's draw time as an ISO date-time. If the WBC is 4.5 to 10.0 inclusive, order nothing. Exclusion: before "
        "ordering, check the newest platelet count (code PLT). If it is below 100 x10^3/uL, do not order any of these "
        "tests; hold them for hematology review."
    ),
}


def _severe(wbc: float) -> bool:
    return wbc > 15.0 or wbc < 3.0


def needs(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> dict[str, Any] | None:
    """What the text requires for this patient, or None if there is no fresh WBC or no platelet count to check."""
    level = newest(fhir, mrn, "WBC", now)
    if level is None or level[1] < now - window:
        return None
    wbc = level[0]
    if 4.5 <= wbc <= 10.0:
        return {"orders": 0, "held": False, "value": wbc}
    plt = newest(fhir, mrn, "PLT", now)
    if plt is None:
        return None
    if plt[0] < PLT_FLOOR:
        return {"orders": 0, "held": True, "value": wbc, "plt": plt[0]}
    severe = _severe(wbc)
    return {
        "orders": 3 if severe else 2,
        "held": False,
        "value": wbc,
        "plt": plt[0],
        "tier": "severe" if severe else "std",
    }


# --- the judge ---
def _d(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _codes(p: dict[str, Any]) -> set[str]:
    coding = _d(p.get("code")).get("coding")
    return {str(_d(c).get("code", "")).strip() for c in coding} if isinstance(coding, list) else set()


def _instant(x: Any) -> datetime | None:
    if not isinstance(x, str) or "T" not in x:
        return None
    try:
        t = datetime.fromisoformat(x.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _order_ok(p: dict[str, Any], code: str, priority: str, due: datetime) -> bool:
    if p.get("resourceType") not in (None, "ServiceRequest") or code not in _codes(p):
        return False
    if len(_codes(p)) != 1 or str(p.get("priority", "")).lower() != priority:
        return False
    t = _instant(p.get("occurrenceDateTime"))
    return t is not None and abs((t - due).total_seconds()) < 60


def accurate(need: dict[str, Any], payloads: list[dict[str, Any]], now: datetime) -> bool:
    """Exactly the required lab orders, each once, with its code, priority and draw time."""
    try:
        if not isinstance(payloads, list):
            return False
        if need["orders"] == 0:
            return not payloads
        if len(payloads) != need["orders"] or not all(isinstance(p, dict) for p in payloads):
            return False
        now = now if now.tzinfo else now.replace(tzinfo=UTC)
        wanted = [(CBC, "stat", now), (WBC_REPEAT, "routine", now + timedelta(hours=RECHECK_HOURS))]
        if need["tier"] == "severe":
            wanted.append((CULTURE, "urgent", now))
        left = list(payloads)
        for code, priority, due in wanted:
            match = next((p for p in left if _order_ok(p, code, priority, due)), None)
            if match is None:
                return False
            left.remove(match)
        return not left
    except Exception:  # noqa: BLE001 - a malformed payload is a wrong answer, never a crash
        return False


# --- the hand-coded rule script (the baseline) ---
def rule_payloads(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> list[dict[str, Any]]:
    level, plt = newest(fhir, mrn, "WBC", now), newest(fhir, mrn, "PLT", now)
    if level is None or level[1] < now - window or 4.5 <= level[0] <= 10.0 or plt is None or plt[0] < PLT_FLOOR:
        return []
    subject = {"reference": mrn}

    def order(code: str, priority: str, at: datetime) -> dict[str, Any]:
        return {
            "resourceType": "ServiceRequest",
            "code": {"coding": [{"system": "http://loinc.org", "code": code}]},
            "priority": priority,
            "occurrenceDateTime": at.isoformat(timespec="seconds"),
            "subject": subject,
        }

    out = [order(CBC, "stat", now), order(WBC_REPEAT, "routine", now + timedelta(hours=RECHECK_HOURS))]
    if _severe(level[0]):
        out.append(order(CULTURE, "urgent", now))
    return out
