"""Results watch: for each new result a ward's protocols cover, the agent applies the protocol and drafts its orders.

Abnormal results are often acted on late or not at all, and protocols still wait for someone to notice the result
(docs/PAIN.md). The watch does the noticing. For each patient on a ward and each protocol, it takes the newest result
the protocol covers, if that result falls inside a time window, and turns it into a task for the gated agent. The
watch never decides what is abnormal or what to order: that stays in the protocol's own text, which the agent applies,
and every order the agent drafts waits for a clinician (medgate.review).
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from medgate.fhir import FhirClient
from medgate.results import clinical_time, compact


@dataclass(frozen=True)
class Protocol:
    name: str  # for example "Potassium replacement"
    code: str  # the code its results carry, as a search takes it, for example "K"
    text: str  # the protocol as the unit writes it


@dataclass(frozen=True)
class Ward:
    now: str  # the moment the watch looks from, ISO 8601
    window_hours: float  # how recent a result must be to count as new
    patients: tuple[str, ...]  # MRNs
    protocols: tuple[Protocol, ...]


@dataclass(frozen=True)
class Event:
    patient: str  # MRN
    protocol: Protocol
    result: dict[str, Any]  # the triggering result in compact form (medgate.results.compact)


def load_ward(path: Path) -> Ward:
    data = cast(dict[str, Any], json.loads(path.read_text()))
    protocols = tuple(Protocol(str(p["name"]), str(p["code"]), str(p["text"])) for p in data["protocols"])
    return Ward(str(data["now"]), float(data["window_hours"]), tuple(map(str, data["patients"])), protocols)


def new_results(ward: Ward, fhir: FhirClient, patients: list[str] | None = None) -> list[Event]:
    """One event per patient and protocol whose newest covered result is inside the window before `ward.now`.

    Results dated after `ward.now` are ignored, so the record reads as it did at that moment. A search that fails
    raises: a watch that silently skips a patient would recreate the problem it exists to solve.
    """
    now = datetime.fromisoformat(ward.now)
    oldest = now - timedelta(hours=ward.window_hours)
    events: list[Event] = []
    for mrn in patients if patients is not None else ward.patients:
        for protocol in ward.protocols:
            fetched = fhir.get(f"{fhir.base}Observation?patient={mrn}&code={protocol.code}&_count=5000&_format=json")
            if fetched.error is not None:
                raise RuntimeError(f"could not search {protocol.code} results for {mrn}: {fetched.error}")
            entries = cast(list[dict[str, Any]], json.loads(str(fetched.data)).get("entry", []))
            resources = [cast(dict[str, Any], entry["resource"]) for entry in entries]
            timed = [(t, r) for r in resources if (t := clinical_time(r)) is not None and t <= now]
            if timed:
                time, newest = max(timed, key=lambda pair: pair[0])
                if time >= oldest:
                    events.append(Event(mrn, protocol, cast(dict[str, Any], compact(newest))))
    return events


def case_for(event: Event, now: str) -> dict[str, Any]:
    """The task the agent gets for one event: the protocol as context, the new result as the question."""
    result = event.result
    quantity = cast(dict[str, Any], result.get("valueQuantity") or {})
    value = f"{quantity.get('value')} {quantity.get('unit', '')}".strip() if quantity else result.get("valueString", "")
    return {
        "id": f"watch:{event.patient}:{event.protocol.code}",
        "context": f"It's {now} now. {event.protocol.text}",
        "instruction": (
            f"New result for patient {event.patient}: {event.protocol.code} {value} at "
            f"{result.get('effectiveDateTime')} (Observation/{result['id']}). Apply the {event.protocol.name} protocol "
            "to it: place the orders it calls for, citing this result, or order nothing if it calls for none. "
            "Finish with the result's value."
        ),
    }
