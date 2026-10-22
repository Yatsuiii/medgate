"""The benchmark's function spec as native tools, for the tool-calling arms (T and TG).

The tool-calling arms see the same nine FHIR functions as the reference arm, as structured tools instead of a JSON
list inside the prompt, plus a calculator and a finish tool. This follows the agent design of MedAgentBench v2
(Chen et al., PSB 2026), written from the paper's description; none of its code is used.
"""

import copy
import re
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlencode

from medgate.gates import SPEC_GRADER_CONFLICTS
from medgate.protocol import FHIR_BASE

# Searches fetch every match and medgate.results orders and trims them, so the agent never works from an arbitrary
# page. 5000 is the size the benchmark's grader fetches with; a search with more matches says so in its results.
FETCH_ALL = 5000
SEARCH_CONTROLS: dict[str, dict[str, Any]] = {
    "_sort": {
        "type": "string",
        "description": "Order of the results: -date for newest first (the default) or date for oldest first.",
    },
    "_count": {"type": "integer", "description": "Show at most this many results (default: as many as fit)."},
}

# FHIR orders can say what they are based on (reasonReference). The order tools offer it so the agent can cite the
# record behind an order; TG's evidence gate then checks every cited record was actually retrieved, and the review
# shows the cited records beside the order.
ORDER_RESOURCES = ("MedicationRequest", "ServiceRequest")
CITATION: dict[str, Any] = {
    "type": "array",
    "items": {"type": "object", "properties": {"reference": {"type": "string"}}},
    "description": 'The records this order is based on, for example [{"reference": "Observation/325493"}].',
}

CALCULATOR: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": (
            "Evaluate an arithmetic expression: numbers, + - * / // % **, parentheses, lists, and the functions "
            "abs, round, min, max, sum, len, floor, ceil, sqrt, hours_between(start, end), days_between(start, end) "
            "and years_between(start, end), where start and end are ISO dates or date-times. "
            "Example: sum([1.8, 2.1, 1.6]) / 3"
        ),
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
}
FINISH: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": "End the task with the final answer, a list of values.",
        "parameters": {
            "type": "object",
            "properties": {"answer": {"type": "array", "items": {"anyOf": [{"type": "number"}, {"type": "string"}]}}},
            "required": ["answer"],
        },
    },
}

_DESCRIPTION_HEAD = re.compile(r"^(\w+)\.(\w+)(?: \(([^)]*)\))?")


@dataclass(frozen=True)
class FhirTool:
    name: str
    method: str  # "GET" or "POST"
    resource: str  # the FHIR resource type the call targets, for example "Observation"
    definition: dict[str, Any]  # the tool definition the model sees, in the OpenAI format


def _name(description: str) -> str:
    """'Observation.Search (Labs) ...' becomes observation_search_labs: the spec's own label for the function."""
    head = _DESCRIPTION_HEAD.match(description)
    if head is None:
        raise ValueError(f"cannot name a tool from the description {description[:40]!r}")
    resource, operation, qualifier = head.groups()
    return "_".join(word.lower() for word in [resource, operation, *(qualifier or "").split()])


def _retype_grader_conflicts(resource: str, write_schema: dict[str, Any]) -> None:
    """In place: type each spec-grader conflict in a write schema as the plain string the grader requires."""
    for conflict_resource, path in SPEC_GRADER_CONFLICTS:
        if conflict_resource != resource:
            continue
        node = write_schema
        *parents, leaf = path.split(".")
        for step in parents:
            node = cast(dict[str, Any], node["properties"][step.removesuffix("[]")])
            if step.endswith("[]"):
                node = cast(dict[str, Any], node["items"])
        cast(dict[str, Any], node["properties"])[leaf] = {"type": "string"}


def fhir_tools(functions: list[dict[str, Any]]) -> dict[str, FhirTool]:
    """One tool per spec entry, keyed by name. Searches also take the standard FHIR _sort and _count controls."""
    tools: dict[str, FhirTool] = {}
    for function in functions:
        method, path = cast(str, function["name"]).split(" ", 1)
        resource = path.rsplit("/", 1)[-1]
        name = _name(cast(str, function["description"]))
        if name in tools:
            raise ValueError(f"two spec entries map to the tool name {name!r}")
        parameters = copy.deepcopy(cast(dict[str, Any], function["parameters"]))
        if method == "GET":
            parameters["properties"] = {**parameters["properties"], **SEARCH_CONTROLS}
        else:
            _retype_grader_conflicts(resource, parameters)
            if resource in ORDER_RESOURCES:
                parameters["properties"]["reasonReference"] = CITATION
        definition = {
            "type": "function",
            "function": {"name": name, "description": function["description"], "parameters": parameters},
        }
        tools[name] = FhirTool(name, method, resource, definition)
    return tools


def tool_definitions(tools: dict[str, FhirTool]) -> list[dict[str, Any]]:
    return [tool.definition for tool in tools.values()] + [CALCULATOR, FINISH]


def search_url(tool: FhirTool, arguments: dict[str, Any], base: str = FHIR_BASE) -> str:
    """The url of a search, as the reference protocol would write it in a GET line (without &_format=json).

    The sort and count controls are applied to the fetched results, not sent to the server, which fetches every match.
    """
    parameters = {
        name: value
        for name, value in arguments.items()
        if name not in SEARCH_CONTROLS and value is not None and value != ""
    }
    return f"{base}{tool.resource}?{urlencode({**parameters, '_count': FETCH_ALL})}"
