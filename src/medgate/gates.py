"""Evidence gates: pure functions that decide whether an action may proceed. No network, so each is unit-testable.

Each gate returns a list of problems. An empty list means the action may proceed.
"""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any, cast

WRITE_RESOURCES = ("Observation", "MedicationRequest", "ServiceRequest")
MAX_PROBLEMS_SHOWN = 3

# Places where the benchmark's own tool spec contradicts its grader, found by reading refsol.py: the spec types
# MedicationRequest dosageInstruction[].route as an object, but the grader requires a plain string ("IV", "oral").
# Enforcing the spec there would steer a model toward failing the grader, so the gate does not check these paths.
SPEC_GRADER_CONFLICTS = frozenset({("MedicationRequest", "dosageInstruction[].route")})

FORMAT_RETRY = (
    "Your response was not a valid action. Reply with exactly one of: GET url?params, "
    "POST url followed by a JSON payload on the next line, or FINISH([answers])."
)

_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
}


@dataclass(frozen=True)
class GateConfig:
    """Which gates are on. All off reproduces the benchmark's reference loop exactly."""

    format_retry: bool = False
    validate_payload: bool = False
    require_evidence: bool = False
    finish_review: bool = False  # the tool agent audits its decision once before its first accepted finish


REFERENCE = GateConfig()
FORMAT_ONLY = GateConfig(format_retry=True)
WITH_VALIDATION = GateConfig(format_retry=True, validate_payload=True)
FULL = GateConfig(format_retry=True, validate_payload=True, require_evidence=True)
WATCH = replace(FULL, finish_review=True)


def resource_type_of(url: str) -> str | None:
    """The FHIR resource a POST url targets, if it is one of the writable resources."""
    last = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return last if last in WRITE_RESOURCES else None


def _type_name(value: Any) -> str:
    return "boolean" if isinstance(value, bool) else type(value).__name__


def _matches(value: Any, expected: str) -> bool:
    if isinstance(value, bool) and expected != "boolean":
        return False
    return isinstance(value, _JSON_TYPES.get(expected, (object,)))


def _walk(value: Any, schema: dict[str, Any], path: str, resource: str) -> Iterator[str]:
    if (resource, path) in SPEC_GRADER_CONFLICTS:
        return
    expected = schema.get("type")
    label = path or "payload"
    if isinstance(expected, str) and not _matches(value, expected):
        yield f"{label}: expected {expected}, got {_type_name(value)}"
        return
    if isinstance(value, dict):
        fields = cast(dict[str, Any], value)
        for name in cast(list[str], schema.get("required", [])):
            if name not in fields:
                yield f"{label}: required field {name!r} is missing"
        for name, sub in cast(dict[str, dict[str, Any]], schema.get("properties", {})).items():
            if name in fields:
                yield from _walk(fields[name], sub, f"{path}.{name}" if path else name, resource)
    elif isinstance(value, list) and "items" in schema:
        for item in cast(list[Any], value):
            yield from _walk(item, cast(dict[str, Any], schema["items"]), f"{path}[]", resource)


def spec_problems(url: str, payload: Any, functions: list[dict[str, Any]]) -> list[str]:
    """Check a POST against the tool spec the prompt gave the model: resource, required fields and value types."""
    resource = resource_type_of(url)
    if resource is None:
        return [f"POST is only allowed for {', '.join(WRITE_RESOURCES)}"]
    if not isinstance(payload, dict):
        return ["the payload must be a JSON object"]
    spec = next((f for f in functions if f.get("name", "").endswith(f"/{resource}") and "POST" in f["name"]), None)
    if spec is None:
        return []
    found = cast(dict[str, Any], payload).get("resourceType")
    if found != resource:
        return [f"resourceType must be {resource!r} to match the url, got {found!r}"]
    return list(_walk(payload, cast(dict[str, Any], spec["parameters"]), "", resource))


def _references(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in cast(dict[str, Any], node).items():
            if key == "reference" and isinstance(value, str):
                yield value
            else:
                yield from _references(value)
    elif isinstance(node, list):
        for item in cast(list[Any], node):
            yield from _references(item)


def _seen(reference: str, evidence_text: str) -> bool:
    """Whether the id in a reference ("Patient/S123" or "S123") appears in what the agent was told or retrieved."""
    return reference.rsplit("/", 1)[-1] in evidence_text


def evidence_problems(payload: Any, evidence_text: str) -> list[str]:
    """Every record the write refers to must already appear in what the agent was told or retrieved."""
    return [
        f"{ref!r} has not been retrieved or given in the question; "
        "look it up first, and do not write if it does not exist"
        for ref in _references(payload)
        if not _seen(ref, evidence_text)
    ]


def write_problems(
    url: str, payload: Any, functions: list[dict[str, Any]], cfg: GateConfig, evidence_text: str
) -> list[str]:
    """Problems with a write under the gates `cfg` turns on. The spec check runs first; evidence only if it passes."""
    problems: list[str] = []
    if cfg.validate_payload:
        problems = spec_problems(url, payload, functions)
    if not problems and cfg.require_evidence:
        problems = evidence_problems(payload, evidence_text)
    return problems


PATIENT_SEARCH_PARAMETERS = ("patient", "subject", "identifier")


def read_problems(parameters: dict[str, Any], evidence_text: str) -> list[str]:
    """A search scoped to one patient must name a patient the agent was told about or has retrieved.

    Only the tool-calling arms use this: their searches arrive as named parameters, while the text protocol's raw
    GET urls are left as the reference loop handles them.
    """
    return [
        f"{name}={value!r} is not a patient given in the question or retrieved so far"
        for name in PATIENT_SEARCH_PARAMETERS
        if isinstance(value := parameters.get(name), str) and not _seen(value, evidence_text)
    ]


def rejection_message(problems: list[str]) -> str:
    shown = "; ".join(problems[:MAX_PROBLEMS_SHOWN])
    return f"POST request rejected: {shown}. Fix the payload and send the corrected POST."


def read_rejection_message(problems: list[str]) -> str:
    shown = "; ".join(problems[:MAX_PROBLEMS_SHOWN])
    return f"Search rejected: {shown}. Search again with an identifier from the question or from earlier results."
