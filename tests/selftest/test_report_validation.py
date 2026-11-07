"""CR5 #2 regression: report row validation used before the API-DISC-05 known-defect handling."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("runs_async", ROOT / "tests" / "http" / "test_runs_async.py")
ra = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ra)

GOOD = {"LABEL": "x", "SOURCE": "AFTER", "ARGUMENT": "a", "CNT": 2, "TOTAL": 3, "METRIC": 0.5,
        "APP_IDS": ["A1", "A2"], "RESULT": "FAIL", "CONFIDENCE": "LOW"}
UNIVERSE = {"A1", "A2", "A3"}


def test_valid_row_passes():
    assert ra.row_problems(GOOD, UNIVERSE) == []


@pytest.mark.parametrize("change", [
    {"METRIC": "x"}, {"METRIC": float("nan")}, {"METRIC": True}, {"CNT": -1}, {"CNT": 4}, {"TOTAL": "3"},
    {"CNT": True}, {"APP_IDS": [1]}, {"APP_IDS": ["A2", "A1"]}, {"APP_IDS": ["A1", "A1"]},
    {"APP_IDS": ["A1", "A2", "A3"]}, {"APP_IDS": ["ZZ"]}, {"TOTAL": 4, "CNT": 0, "APP_IDS": []},
    {"LABEL": ""}, {"ARGUMENT": None}, {"RESULT": "ERROR"},
])
def test_malformed_values_are_rejected(change):
    assert ra.row_problems({**GOOD, **change}, UNIVERSE), change
