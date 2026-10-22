"""The held-out oracle's checks (analysis/heldout_run.py), against the real order shapes of the demo replay."""

import copy
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "analysis" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUN = load("heldout_run")
NOW = datetime.fromisoformat("2023-11-13T10:15:00+00:00")
REPLAY = json.loads((ROOT / "demo" / "replay.json").read_text())["watch"]


def orders_of(key: str) -> list[dict[str, Any]]:
    """The payloads a correct scripted run for this demo event writes, in the shapes the agent really uses."""
    calls = [c for turn in REPLAY[key] for c in turn["calls"] if c["name"].endswith("_create")]
    return [json.loads(c["arguments"]) for c in calls]


POTASSIUM = orders_of("watch:S6550627:K")  # K 3.1: 40 mEq oral and the paired stat level
MAGNESIUM = orders_of("watch:S3084624:MG")  # Mg 1.8: 1 g IV over 1 hour


def test_the_demo_replays_pass_the_oracle() -> None:
    assert RUN.potassium_ok(POTASSIUM, 3.1, NOW) and RUN.magnesium_ok(MAGNESIUM, 1.8)


def test_wrong_dose_duration_route_or_time_fail_the_oracle() -> None:
    low = copy.deepcopy(MAGNESIUM)
    low[0]["dosageInstruction"][0]["doseAndRate"][0]["doseQuantity"]["value"] = 2
    no_rate = copy.deepcopy(MAGNESIUM)
    del no_rate[0]["dosageInstruction"][0]["doseAndRate"][0]["rateQuantity"]
    oral = copy.deepcopy(MAGNESIUM)
    oral[0]["dosageInstruction"][0]["route"] = "oral"
    assert not RUN.magnesium_ok(low, 1.8) and not RUN.magnesium_ok(no_rate, 1.8) and not RUN.magnesium_ok(oral, 1.8)
    same_day = copy.deepcopy(POTASSIUM)
    same_day[1]["occurrenceDateTime"] = "2023-11-13T08:00:00+00:00"
    assert not RUN.potassium_ok(same_day, 3.1, NOW) and not RUN.potassium_ok(POTASSIUM[:1], 3.1, NOW)
    assert not RUN.potassium_ok(POTASSIUM, 3.0, NOW)  # 3.0 needs 50 mEq


@pytest.mark.parametrize(("value", "grams"), [(1.9, 1), (1.5, 1), (1.4, 2), (1.0, 2), (0.9, 4)])
def test_magnesium_bands(value: float, grams: int) -> None:
    order = copy.deepcopy(MAGNESIUM)
    dose = order[0]["dosageInstruction"][0]["doseAndRate"][0]
    dose["doseQuantity"]["value"] = dose["rateQuantity"]["value"] = grams
    assert RUN.magnesium_ok(order, value)


def test_runs_are_classified_against_the_need() -> None:
    mg_need = {"orders": 1, "value": 1.8}
    assert RUN.judge(mg_need, "MG", [], NOW)["kind"] == "miss"
    assert RUN.judge(mg_need, "MG", MAGNESIUM, NOW) == {"kind": "complete", "payload_ok": True}
    k_need = {"orders": 2, "value": 3.1}
    assert RUN.judge(k_need, "K", POTASSIUM[:1], NOW)["kind"] == "incomplete"
    assert RUN.judge(k_need, "K", POTASSIUM, NOW) == {"kind": "complete", "payload_ok": True}
    assert RUN.judge({"orders": 0, "value": 4.2}, "K", [], NOW)["kind"] == "ok_none"
    assert RUN.judge({"orders": 0, "value": 4.2}, "K", POTASSIUM[:1], NOW)["kind"] == "false_order"
    assert RUN.judge({"orders": 0, "value": 1.8, "held": True}, "MG", [], NOW)["kind"] == "held_ok"


def totals_of(misses: int, false_orders: int, accurate: int, complete: int = 20, incomplete: int = 0) -> dict[str, Any]:
    return {
        "runs": 100, "needs_orders_runs": 60, "misses": misses, "incomplete": incomplete, "complete": complete,
        "payload_ok": accurate, "quiet_runs": 160, "false_orders": false_orders, "model_calls": 5.0,
    }  # fmt: skip


def test_the_verdict_applies_the_frozen_criteria() -> None:
    base = totals_of(10, 2, 18)
    assert RUN.verdict(base, totals_of(5, 5, 18)).startswith("THE CHANGE WORKS")
    assert RUN.verdict(base, totals_of(5, 6, 18)).startswith("CAUTION")  # false orders baseline + 4
    assert RUN.verdict(base, totals_of(5, 5, 15)).startswith("CAUTION")  # accuracy 6 points lower
    assert RUN.verdict(base, totals_of(5, 5, 18, incomplete=1)).startswith("CAUTION")
    assert RUN.verdict(base, totals_of(8, 2, 18)).startswith("THE CHANGE FAILS")  # more than 75% of the misses
    assert RUN.verdict(base, totals_of(6, 10, 18)).startswith("THE CHANGE FAILS")  # +8 false orders
    assert RUN.verdict(totals_of(5, 2, 18), totals_of(0, 2, 18)).startswith("INCONCLUSIVE")


def test_malformed_payloads_count_as_inaccurate_instead_of_crashing_a_run() -> None:
    for bad in (
        {"dosageInstruction": ["1 g IV over 1 hour"]},
        {"dosageInstruction": [{"route": None, "doseAndRate": "1 g"}]},
        {
            "dosageInstruction": [{"doseAndRate": [{"doseQuantity": "40 mEq"}]}],
            "medicationCodeableConcept": "0338-1715-40",
        },
        {"medicationCodeableConcept": {"coding": "x"}, "code": ["2823-3"], "occurrenceDateTime": 5},
        {"dosageInstruction": [{"doseAndRate": [{"doseQuantity": {"value": "40", "unit": "mEq"}}]}]},
    ):
        assert RUN.magnesium_ok([bad], 1.8) is False and RUN.potassium_ok([bad], 3.1, NOW) is False
        assert RUN.judge({"orders": 1, "value": 1.8}, "MG", [bad], NOW) == {"kind": "complete", "payload_ok": False}
