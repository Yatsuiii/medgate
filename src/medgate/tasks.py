"""Loading the benchmark's tasks and tool definitions."""

import json
from pathlib import Path
from typing import Any, cast

DEFAULT_DATA = Path(__file__).resolve().parents[2] / "vendor" / "MedAgentBench" / "data" / "medagentbench"


def load_tasks(path: Path = DEFAULT_DATA / "test_data_v2.json") -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], json.loads(path.read_text()))


def load_functions(path: Path = DEFAULT_DATA / "funcs_v1.json") -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], json.loads(path.read_text()))
