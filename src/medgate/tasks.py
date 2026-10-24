"""Loading the benchmark's tasks and tool definitions."""

import json
from pathlib import Path
from typing import Any, cast

DEFAULT_DATA = Path(__file__).resolve().parents[2] / "vendor" / "MedAgentBench" / "data" / "medagentbench"


def load_tasks(path: Path = DEFAULT_DATA / "test_data_v2.json") -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], json.loads(path.read_text()))


def load_functions(path: Path = DEFAULT_DATA / "funcs_v1.json") -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], json.loads(path.read_text()))


_ORDER_TOOL = "POST {api_base}/MedicationRequest"
_TIMING = {
    "type": "object",
    "description": "How often and for how long the dose is given. Leave it out for a single dose.",
    "properties": {
        "repeat": {
            "type": "object",
            "properties": {
                "frequency": {"type": "integer", "description": "Doses per period, such as 2 for twice a day"},
                "period": {"type": "number", "description": "Length of the period, such as 1 for each day"},
                "periodUnit": {"type": "string", "description": 'Unit of the period: "h", "d" or "wk"'},
                "boundsDuration": {
                    "type": "object",
                    "description": "How long the whole course lasts, such as 2 days",
                    "properties": {
                        "value": {"type": "number"},
                        "unit": {"type": "string", "description": '"h" or "d"'},
                    },
                },
            },
        }
    },
}


_PRIORITY = {"type": "string", "description": 'How urgent the order is: "routine", "urgent", "asap" or "stat"'}


def watch_functions(path: Path = DEFAULT_DATA / "funcs_v1.json") -> list[dict[str, Any]]:
    """The tool definitions the results watch gives its agent: the benchmark's, plus how often and how long a
    medication is given, and its priority. The benchmark's MedicationRequest tool has no field for any of them, so an
    ordinary order such as "1 g twice daily for 2 days, routine" cannot be written. The benchmark arms keep
    `load_functions` unchanged.
    """
    functions = load_functions(path)
    for tool in functions:
        if tool["name"] == _ORDER_TOOL:
            dosage = tool["parameters"]["properties"]["dosageInstruction"]["items"]["properties"]
            dosage["timing"] = _TIMING
            # An order with no route or no dose is not an order a person can sign.
            tool["parameters"]["properties"]["dosageInstruction"]["items"]["required"] = ["route", "doseAndRate"]
            dose = dosage["doseAndRate"]["items"]
            dose["required"] = ["doseQuantity"]
            dose["properties"]["rateQuantity"]["description"] = (
                "For a drug given over time: how long it runs (such as 1 h) or how fast. Leave out for a single dose."
            )
            tool["parameters"]["properties"]["priority"] = _PRIORITY
    return functions
