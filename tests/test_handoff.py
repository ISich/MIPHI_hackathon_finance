"""Handoff tests: trusted D1/D4 boundary, no DuckDB needed for these cases."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from decision_diff.handoff import default_policy, execute_trusted_checks, process_application
from decision_diff.procedure_api import ProcedureContractError

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _docs():
    before = json.loads((EXAMPLES / "I32554354_other.json").read_text(encoding="utf-8"))
    after = json.loads((EXAMPLES / "I32554354.json").read_text(encoding="utf-8"))
    return before, after


def test_process_application_matches_real_pair():
    before, after = _docs()
    result = process_application(before=before, after=after, app_id="I32554354")
    assert len(result["normalized"]) == 264
    assert len(result["comparison"]) == 141
    assert result["segment"]["DECISION_CHANGED"] == 1
    assert result["segment"]["DECISION_BEFORE"] == "REJECT"
    assert result["segment"]["DECISION_AFTER"] == "APPROVE"


def test_policy_has_independent_copy():
    a = default_policy()
    a["excluded_paths"].append("altered")
    assert "altered" not in default_policy()["excluded_paths"]


def test_invalid_app_id_is_rejected():
    with pytest.raises(ValueError, match="app_id"):
        process_application(before={}, after={}, app_id="")


def test_checks_failure_is_execution_diagnostic_not_business_fail():
    class FakeResult:
        rows = []
        diagnostics = [{"check": "broken", "error_type": "RuntimeError", "message": "boom"}]
        timings = {"broken": 0.01}

    with patch("decision_diff.handoff.run_checks", return_value=FakeResult()):
        result = execute_trusted_checks(mart=object(), check_files=["broken.py"])
    assert result["rows"] == []
    assert not result["complete"]
    assert result["diagnostics"][0]["check"] == "broken"


def test_success_with_zero_rows_is_complete():
    class FakeResult:
        rows = []
        diagnostics = []
        timings = {"empty": 0.01}

    with patch("decision_diff.handoff.run_checks", return_value=FakeResult()):
        result = execute_trusted_checks(mart=object(), check_files=["empty.py"])
    assert result["complete"] is True
    assert result["rows"] == []


def test_bad_normalization_policy_rejected():
    before, after = _docs()
    with pytest.raises(ProcedureContractError):
        process_application(before=before, after=after, app_id="I32554354", normalization_params={"surprise": 1})
