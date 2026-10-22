"""A held-out ward for testing changes to the results watch, with an independent oracle for what each event needs.

The demo ward's events were used to find the watch's problems, so a fix is tested on other patients. The oracle applies
the two demo protocols' written rules to the record (potassium below 3.5; magnesium at or below 1.9 unless the newest
eGFR is below 45) to say how many orders an event needs. It lives here, in analysis code, and never in the product:
the agent applies the protocol text, and code must not decide what is abnormal.

Usage, from the repository root with the FHIR server up:
    uv run python -I analysis/heldout.py build runs/heldout_ward.json
"""

import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from medgate.fhir import FhirClient
from medgate.protocol import FHIR_BASE
from medgate.results import clinical_time

DEMO = Path("demo")
SEED = 0
NORMAL_PATIENTS_KEPT = 14  # patients with no actionable event, sampled so a fix is also checked for false orders


def newest(fhir: FhirClient, mrn: str, code: str, now: datetime) -> tuple[float, datetime] | None:
    """The newest value of a lab on or before `now`, as (value, time), or None."""
    url = f"{FHIR_BASE}Observation?patient={mrn}&code={code}&_count=5000&_format=json"
    entries = json.loads(str(fhir.get(url).data)).get("entry", [])
    found = [(t, r) for e in entries if (r := e["resource"]) and (t := clinical_time(r)) is not None and t <= now]
    if not found:
        return None
    time, resource = max(found, key=lambda pair: pair[0])
    value = (resource.get("valueQuantity") or {}).get("value")
    return None if value is None else (float(value), time)


def expected_orders(
    k: tuple[float, datetime] | None, mg: tuple[float, datetime] | None, egfr: float | None
) -> dict[str, Any]:
    """What each protocol needs for this patient's newest results (None for a protocol with no new result)."""
    need: dict[str, Any] = {}
    if k is not None:
        need["K"] = {"orders": 2 if k[0] < 3.5 else 0, "value": k[0]}
    if mg is not None:
        held = egfr is not None and egfr < 45
        need["MG"] = {"orders": 1 if mg[0] <= 1.9 and not held else 0, "value": mg[0], "held": mg[0] <= 1.9 and held}
    return need


def scan_patient(fhir: FhirClient, mrn: str, now: datetime, window: timedelta) -> dict[str, Any]:
    k, mg, egfr = (newest(fhir, mrn, code, now) for code in ("K", "MG", "EGFR"))
    fresh = lambda r: r if r is not None and r[1] >= now - window else None  # noqa: E731
    k, mg = fresh(k), fresh(mg)
    usable_mg = mg if mg is None or mg[0] > 1.9 or egfr is not None else None  # no eGFR: the exclusion is ambiguous
    return {"mrn": mrn, "need": expected_orders(k, usable_mg, None if egfr is None else egfr[0])}


def build(out: Path) -> None:
    ward = json.loads((DEMO / "ward.json").read_text())
    now, window = datetime.fromisoformat(ward["now"]), timedelta(hours=float(ward["window_hours"]))
    fhir = FhirClient()
    patients = json.loads(str(fhir.get(f"{FHIR_BASE}Patient?_count=1000&_elements=id&_format=json").data))["entry"]
    mrns = sorted(e["resource"]["id"] for e in patients if e["resource"]["id"] not in ward["patients"])
    with ThreadPoolExecutor(8) as pool:
        scans = list(pool.map(lambda m: scan_patient(fhir, m, now, window), mrns))
    actionable = [s for s in scans if any(n["orders"] > 0 or n.get("held") for n in s["need"].values())]
    quiet = [s for s in scans if s["need"] and s not in actionable]
    chosen = actionable + random.Random(SEED).sample(quiet, min(NORMAL_PATIENTS_KEPT, len(quiet)))
    events = [{"patient": s["mrn"], "protocol": p, **n} for s in chosen for p, n in s["need"].items()]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                **{k: ward[k] for k in ("now", "window_hours", "protocols")},
                "patients": [s["mrn"] for s in chosen],
                "events": events,
            },
            indent=1,
        )
        + "\n"
    )
    print(
        f"{len(mrns)} patients scanned, {len(actionable)} with an actionable or held event, "
        f"{len(quiet)} with only normal results; "
        f"kept {len(chosen)} patients, {len(events)} events: "
        f"{sum(e['orders'] > 0 for e in events)} need orders, {sum(bool(e.get('held')) for e in events)} held, "
        f"{sum(e['orders'] == 0 and not e.get('held') for e in events)} need nothing"
    )


if __name__ == "__main__":
    if sys.argv[1:2] != ["build"]:
        raise SystemExit(__doc__)
    build(Path(sys.argv[2]))
