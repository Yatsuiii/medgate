"""Grading with the benchmark's own grader.

The grader (vendor/refsol.py) is withheld by its authors to limit contamination: it stays inside vendor/, is never
copied, committed or published, and is loaded from there at run time.
"""

import importlib.util
import sys
import threading
import types
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from medgate.loop import TaskResult
from medgate.protocol import FHIR_BASE

VENDOR = Path(__file__).resolve().parents[2] / "vendor"
GRADER_UTILS = VENDOR / "MedAgentBench" / "src" / "server" / "tasks" / "medagentbench" / "utils.py"
GRADER = VENDOR / "refsol.py"
_PACKAGE = "medagentbench_grader"  # refsol.py does `from .utils import *`, so both modules load into one package


_LOAD_LOCK = threading.Lock()


def _grader() -> Any:
    """The loaded grader. Loading is serialized: two threads grading at once must not each build and half-replace it."""
    with _LOAD_LOCK:
        return _load_grader()


@cache
def _load_grader() -> Any:
    package = types.ModuleType(_PACKAGE)
    package.__path__ = []
    sys.modules[_PACKAGE] = package
    for name, path in (("utils", GRADER_UTILS), ("refsol", GRADER)):
        spec = importlib.util.spec_from_file_location(f"{_PACKAGE}.{name}", path)
        if spec is None or spec.loader is None:
            raise FileNotFoundError(f"cannot load the grader from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return sys.modules[f"{_PACKAGE}.refsol"]


def grade(case: dict[str, Any], result: TaskResult, fhir_base: str = FHIR_BASE) -> bool:
    """True when the benchmark grader accepts the run. A run that never finished is incorrect, as in the reference."""
    if result.result is None:
        return False
    outcome = SimpleNamespace(
        history=[SimpleNamespace(role=m["role"], content=m["content"]) for m in result.history],
        result=result.result,
    )
    grader_for_category = getattr(_grader(), case["id"].split("_")[0])
    try:
        return grader_for_category(case, outcome, fhir_base) is True
    except Exception:  # noqa: BLE001 - the reference counts any grader exception as incorrect
        return False
