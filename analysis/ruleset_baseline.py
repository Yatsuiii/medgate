"""B1 of docs/RULESET_PREREG.md: a hand-coded rule script that drafts the two protocols' orders with no model.

Usage, from the repository root with the FHIR server up and runs/heldout_ward.json built:
    uv run python -I analysis/ruleset_baseline.py runs/heldout_ward.json
Thresholds are those of the protocol texts in demo/ward.json. The judge is the one that scored the agent.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from heldout_run import judge, totals  # noqa: E402

from medgate.fhir import FhirClient  # noqa: E402
from medgate.protocol import FHIR_BASE  # noqa: E402
from medgate.results import clinical_time  # noqa: E402


def newest(fhir: FhirClient, mrn: str, code: str, now: datetime) -> tuple[float, str] | None:
    url = f"{FHIR_BASE}Observation?patient={mrn}&code={code}&_count=5000&_format=json"
    found = []
    for entry in json.loads(str(fhir.get(url).data)).get("entry", []):
        res = entry["resource"]
        t, q = clinical_time(res), (res.get("valueQuantity") or {}).get("value")
        if t is not None and t <= now and q is not None:
            found.append((t, float(q), str(res["id"])))
    return None if not found else max(found)[1:]


# --- the rules: one function per protocol ---
def _med(ndc: str, route: str, dose: dict[str, Any], mrn: str, obs: str, now: datetime) -> dict[str, Any]:
    return {
        "medicationCodeableConcept": {"coding": [{"code": ndc}]},
        "authoredOn": now.isoformat(timespec="seconds"),
        "dosageInstruction": [{"route": route, "doseAndRate": [dose]}],
        "subject": {"reference": mrn},
        "reasonReference": [{"reference": f"Observation/{obs}"}],
    }


def potassium(k: float, obs: str, mrn: str, now: datetime) -> list[dict[str, Any]]:
    if k >= 3.5:
        return []
    mEq = {"doseQuantity": {"value": round((3.5 - k) / 0.1 * 10, 1), "unit": "mEq"}}
    draw = {
        "code": {"coding": [{"code": "2823-3"}]},
        "priority": "stat",
        "occurrenceDateTime": (now + timedelta(days=1)).strftime("%Y-%m-%dT08:00:00+00:00"),
        "subject": {"reference": mrn},
        "reasonReference": [{"reference": f"Observation/{obs}"}],
    }
    return [_med("40032-917-01", "oral", mEq, mrn, obs, now), draw]


def magnesium(mg: float, obs: str, egfr: float | None, mrn: str, now: datetime) -> list[dict[str, Any]]:
    if mg > 1.9 or (egfr is not None and egfr < 45):
        return []
    g = 1 if mg >= 1.5 else 2 if mg >= 1.0 else 4
    dose = {"doseQuantity": {"value": g, "unit": "g"}, "rateQuantity": {"value": g, "unit": "h"}}
    return [_med("0338-1715-40", "IV", dose, mrn, obs, now)]


def main(ward_file: Path) -> None:
    spec = json.loads(ward_file.read_text())
    now, fhir = datetime.fromisoformat(spec["now"]), FhirClient()
    rows = []
    for need in spec["events"]:
        mrn, code = need["patient"], need["protocol"]
        got = newest(fhir, mrn, code, now)
        assert got is not None
        value, obs = got
        egfr = newest(fhir, mrn, "EGFR", now)
        payloads = (
            potassium(value, obs, mrn, now)
            if code == "K"
            else magnesium(value, obs, None if egfr is None else egfr[0], mrn, now)
        )
        rows.append(
            {
                "event": f"{mrn}:{code}",
                "need": need,
                "model_calls": 0,
                "orders": len(payloads),
                **judge(need, code, payloads, now),
            }
        )
    t = totals(rows)
    print(json.dumps(t, indent=1))
    miss = [r["event"] for r in rows if r["kind"] in ("miss", "incomplete", "false_order") or r["payload_ok"] is False]
    print("events with any failure:", miss or "none")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
