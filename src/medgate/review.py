"""Review before anything reaches the chart: the writes a run attempted become proposals, and only approved ones
are written.

The agent loops never send writes, as in the benchmark. proposals() turns each write a run attempted into a Proposal:
its payload, what the gates found, and every record it cites read back from the server, so the evidence sits beside
the order. commit() writes one approved proposal as conformant FHIR and reads it back, reporting anything the server
did not store as sent. This matters: the benchmark's FHIR server accepts a medication route given as plain text and
silently drops it, so the order is stored without its route.
"""

import copy
import json
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any, cast

from medgate import gates
from medgate.fhir import FhirClient
from medgate.llm import Message
from medgate.protocol import POST_ACCEPTED, Post, parse_reply
from medgate.results import compact


@dataclass(frozen=True)
class Proposal:
    resource: str  # the FHIR resource type, for example "MedicationRequest"
    payload: dict[str, Any]  # as the agent wrote it, in the benchmark's shapes
    findings: str | None  # the gates' rejection message; None when the gates accepted the write
    evidence: tuple[str, ...]  # each cited record, read back from the server, as one compact JSON line
    superseded: bool = False  # a later draft in the same run has the same resource type and code and passed the gates


@dataclass(frozen=True)
class Committed:
    reference: str  # the stored resource, for example "MedicationRequest/786002"
    dropped: tuple[str, ...]  # paths the server did not store as sent; empty when the write round-trips


def proposals(history: list[Message], fhir: FhirClient) -> list[Proposal]:
    """Every write a run attempted, in order. A write whose payload did not parse leaves nothing to review."""
    found: list[Proposal] = []
    for message, reply in zip(history, history[1:], strict=False):
        action = parse_reply(message["content"]) if message["role"] == "agent" else None
        body: object = action.payload if isinstance(action, Post) else None
        if not isinstance(action, Post) or not isinstance(body, dict):
            continue
        payload = cast(dict[str, Any], body)
        resource = gates.resource_type_of(action.url) or str(payload.get("resourceType", ""))
        findings = None if reply["content"] == POST_ACCEPTED else reply["content"]
        found.append(Proposal(resource, payload, findings, tuple(_cited(payload, fhir))))
    return mark_superseded(found)


def _code_of(proposal: Proposal) -> str | None:
    """The order's own code (the drug's or the test's), the first coding of its medication or code concept."""
    for field in ("medicationCodeableConcept", "code"):
        concept = proposal.payload.get(field)
        codings = cast(dict[str, Any], concept).get("coding") if isinstance(concept, dict) else None
        if isinstance(codings, list) and codings and isinstance(codings[0], dict):
            code = cast(dict[str, Any], codings[0]).get("code")
            if isinstance(code, str):
                return code
    return None


def mark_superseded(drafts: list[Proposal]) -> list[Proposal]:
    """Mark each draft that a later draft of the same resource type and code replaces, without removing anything.

    An agent that notices a mistake in an order it has drafted can only create a new one. Both stay visible, so the
    reviewer sees which is the later version instead of two orders that look equally current. A draft the gates
    rejected is never marked and never marks another: it cannot be committed, so it replaces nothing.
    """
    marked: list[Proposal] = []
    for i, draft in enumerate(drafts):
        code = _code_of(draft)
        later = any(
            code is not None and d.findings is None and d.resource == draft.resource and _code_of(d) == code
            for d in drafts[i + 1 :]
        )
        marked.append(replace(draft, superseded=True) if later and draft.findings is None else draft)
    return marked


def _cited(payload: dict[str, Any], fhir: FhirClient) -> Iterator[str]:
    for citation in cast(list[Any], payload.get("reasonReference") or []):
        reference = cast(dict[str, Any], citation).get("reference") if isinstance(citation, dict) else None
        if not isinstance(reference, str):
            continue
        fetched = fhir.get(f"{fhir.base}{reference}?_format=json")
        if fetched.error is not None:
            yield f"{reference}: could not be read ({fetched.error})"
        else:
            yield json.dumps(compact(json.loads(str(fetched.data))), separators=(",", ":"), ensure_ascii=False)


def to_fhir(resource: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The payload in conformant FHIR. The benchmark's spec and grader use two shapes FHIR does not: a medication
    route as plain text (FHIR: a CodeableConcept; see gates.SPEC_GRADER_CONFLICTS) and a ServiceRequest note as one
    object (FHIR: a list of Annotations).
    """
    converted = copy.deepcopy(payload)
    if resource == "MedicationRequest":
        for dosage in cast(list[Any], converted.get("dosageInstruction") or []):
            if isinstance(dosage, dict) and isinstance(route := cast(dict[str, Any], dosage).get("route"), str):
                cast(dict[str, Any], dosage)["route"] = {"text": route}
    if resource == "ServiceRequest" and isinstance(converted.get("note"), dict):
        converted["note"] = [converted["note"]]
    return converted


def _dropped(sent: Any, stored: Any, path: str) -> Iterator[str]:
    """Paths of `sent` that `stored` does not hold as sent. Fields the server adds are ignored."""
    if isinstance(sent, dict):
        if not isinstance(stored, dict):
            yield path or "payload"
            return
        for key, value in cast(dict[str, Any], sent).items():
            yield from _dropped(value, cast(dict[str, Any], stored).get(key), f"{path}.{key}" if path else key)
    elif isinstance(sent, list):
        items, kept = cast(list[Any], sent), cast(list[Any], stored) if isinstance(stored, list) else []
        if len(kept) < len(items):
            yield path
            return
        for i, (a, b) in enumerate(zip(items, kept, strict=False)):
            yield from _dropped(a, b, f"{path}[{i}]")
    elif sent != stored:
        yield path


def commit(proposal: Proposal, fhir: FhirClient, override: bool = False) -> Committed:
    """Write one approved proposal and read it back. A proposal the gates rejected is refused unless overridden."""
    if proposal.findings is not None and not override:
        raise ValueError(f"the gates rejected this write: {proposal.findings}")
    sent = to_fhir(proposal.resource, proposal.payload)
    reference = fhir.create(proposal.resource, sent)
    return Committed(reference, tuple(_dropped(sent, fhir.read(reference), "")))
