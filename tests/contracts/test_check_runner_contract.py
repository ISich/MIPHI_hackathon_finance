"""D4 `check_runner` @ pinned core vs docs/contracts/execution.md and PRD §10 / AC-14.

All checks below are *authored check files* executed through the real runner on a
real DuckDB mart; they are inputs, not doubles of the core.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from support.fixtures import pair, run_real_pipeline
from support.http_api import known_defect

pytestmark = pytest.mark.contract

ROW = ('{"LABEL": "x", "SOURCE": "AFTER", "ARGUMENT": "a", "CNT": 1, "TOTAL": mart.total_apps(), '
       '"METRIC": 0.5, "APP_IDS": %s, "RESULT": "%s", "CONFIDENCE": "%s"}')


def write_check(folder: Path, name: str, body: str, check_id: str | None = None, params: str = "{}") -> Path:
    path = folder / f"check_{name}.py"
    path.write_text(textwrap.dedent(body) + f'\nCHECK = {{"id": "{check_id or name}", "label": "{name}", '
                    f'"params": {params}, "entrypoint": run}}\n', encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return run_real_pipeline(tmp_path_factory.mktemp("runner"), [pair("R1"), pair("R2")]).db


def run(db, paths, overrides=None):
    from decision_diff.check_runner import run_checks
    from decision_diff.mart import DuckDBMart

    with DuckDBMart(db) as mart:
        return run_checks(mart, paths, overrides)


def test_business_fail_is_a_row_not_a_diagnostic(db, tmp_path):
    p = write_check(tmp_path, "biz_fail", "def run(mart, params):\n    return [" + ROW % ('["R1"]', "FAIL", "LOW") + "]\n")
    result = run(db, [p])
    assert result.diagnostics == []
    assert [r["RESULT"] for r in result.rows] == ["FAIL"]
    assert result.rows[0]["CONFIDENCE"] == "LOW"  # LOW kept, verdict not changed


def test_exception_is_execution_error_not_fail_or_pass(db, tmp_path):
    p = write_check(tmp_path, "boom", "def run(mart, params):\n    raise RuntimeError('boom')\n")
    ok = write_check(tmp_path, "ok", "def run(mart, params):\n    return [" + ROW % ("[]", "PASS", "HIGH") + "]\n")
    result = run(db, [p, ok])
    assert [d["check"] for d in result.diagnostics] == ["boom"]
    assert result.diagnostics[0]["error_type"] == "RuntimeError"
    assert [r["RESULT"] for r in result.rows] == ["PASS"]  # other checks still ran


@pytest.mark.parametrize("bad_row, why", [
    (ROW % ('["R1"]', "ERROR", "HIGH"), "RESULT outside PASS/FAIL"),
    (ROW % ('["R1"]', "FAIL", "MEDIUM"), "CONFIDENCE outside HIGH/LOW"),
    (ROW % ('"R1"', "FAIL", "HIGH"), "APP_IDS not a list"),
    ('{"LABEL": "x"}', "missing fields"),
])
def test_invalid_output_is_diagnosed_and_no_rows_published(db, tmp_path, bad_row, why):
    p = write_check(tmp_path, "bad", "def run(mart, params):\n    return [" + ROW % ("[]", "PASS", "HIGH")
                    + ", " + bad_row + "]\n")
    result = run(db, [p])
    assert result.rows == [], why
    assert len(result.diagnostics) == 1


def test_non_list_output_is_diagnosed(db, tmp_path):
    p = write_check(tmp_path, "dict_out", "def run(mart, params):\n    return {'RESULT': 'PASS'}\n")
    result = run(db, [p])
    assert result.rows == [] and len(result.diagnostics) == 1


@pytest.mark.parametrize("body", [
    "raise ImportError('broken import')\ndef run(mart, params):\n    return []\n",
    "def run(mart, params):\n    return []\n",  # module without CHECK
])
def test_import_error_and_missing_check_are_diagnosed(db, tmp_path, body):
    path = tmp_path / "check_broken.py"
    path.write_text(body, encoding="utf-8")
    result = run(db, [path])
    assert result.rows == [] and len(result.diagnostics) == 1


def test_duplicate_check_id_does_not_overwrite_first(db, tmp_path):
    a = write_check(tmp_path, "first", "def run(mart, params):\n    return [" + ROW % ("[]", "PASS", "HIGH") + "]\n",
                    check_id="same")
    b = write_check(tmp_path, "second", "def run(mart, params):\n    return [" + ROW % ("[]", "FAIL", "HIGH") + "]\n",
                    check_id="same")
    result = run(db, [a, b])
    assert [r["RESULT"] for r in result.rows] == ["PASS"]
    assert len(result.diagnostics) == 1 and "Duplicate" in result.diagnostics[0]["message"]


def test_overrides_do_not_mutate_check_defaults(db, tmp_path):
    from decision_diff.check_runner import load_check

    p = write_check(tmp_path, "params", "def run(mart, params):\n    return [" + ROW % ("[]", "PASS", "HIGH") + "]\n",
                    params='{"threshold": 1}')
    run(db, [p], {"params": {"threshold": 9}})
    assert load_check(p)["params"] == {"threshold": 1}


def test_nested_params_are_not_shared_between_runs(db, tmp_path):
    """CR #9: exercise the real runner lifecycle (run_checks twice, with an override in between).
    A check mutating a nested default must not leak into the next execution."""
    body = ("SHARED = {'seen': []}\n"
            "def run(mart, params):\n"
            "    params['nested']['seen'].append(1)\n"
            "    return [" + ROW % ("[]", "PASS", "HIGH") + " | {'CNT': len(params['nested']['seen'])}]\n")
    p = write_check(tmp_path, "nested", body, params="{'nested': SHARED}")
    first = run(db, [p])
    second = run(db, [p], {"nested": {"threshold": 1}})  # override keyed by CHECK.id
    third = run(db, [p])
    assert first.diagnostics == second.diagnostics == third.diagnostics == []
    assert [r["CNT"] for r in (*first.rows, *second.rows, *third.rows)] == [1, 1, 1]


def test_successful_empty_result_is_not_a_fake_pass(db, tmp_path):
    p = write_check(tmp_path, "empty", "def run(mart, params):\n    return []\n")
    result = run(db, [p])
    assert result.rows == [] and result.diagnostics == []
    assert "empty" in result.timings  # the only trace that it ran


def test_execution_registry_has_status_per_check(db, tmp_path):
    p = write_check(tmp_path, "empty2", "def run(mart, params):\n    return []\n")
    result = run(db, [p])
    assert result.rows == [] and result.diagnostics == [] and "empty2" in result.timings
    executions = getattr(result, "executions", None)
    known_defect(executions is None,
                 "DISC-06: run_checks has no per-check execution record (execution_status, row count)")
    assert executions[0]["execution_status"] == "SUCCESS" and executions[0]["row_count"] == 0


HANG_DRIVER = """
import sys
from decision_diff.check_runner import run_checks
from decision_diff.mart import DuckDBMart
with DuckDBMart(sys.argv[1]) as mart:
    result = run_checks(mart, [sys.argv[2]])
print("DIAG", result.diagnostics)
"""


@pytest.mark.slow
def test_runner_enforces_timeout_on_hanging_check(db, tmp_path):
    """CR #11: behaviour, not a parameter name. A check sleeping for an hour must be stopped and reported as a
    timeout execution error within a bounded wall time (bound: 20 s)."""
    import subprocess
    import sys

    p = write_check(tmp_path, "hang", "import time\ndef run(mart, params):\n    time.sleep(3600)\n    return []\n")
    driver = tmp_path / "driver.py"
    driver.write_text(HANG_DRIVER, encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(driver), str(db), str(p)], stdout=subprocess.PIPE, text=True)
    try:
        out, _ = proc.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        known_defect(True, "DISC-07: run_checks has no timeout; a hanging check blocks the run (bounded 20 s)")
    assert proc.returncode == 0 and "DIAG" in out
    assert "timeout" in out.lower(), out


def test_app_ids_outside_run_are_rejected(db, tmp_path):
    p = write_check(tmp_path, "alien", "def run(mart, params):\n    return [" + ROW % ('["NOT_IN_RUN"]', "FAIL", "HIGH")
                    + "]\n")
    result = run(db, [p])
    known_defect(len(result.rows) == 1 and result.rows[0]["APP_IDS"] == ["NOT_IN_RUN"] and not result.diagnostics,
                 "DISC-08: APP_IDS outside the current Run are accepted (PRD §10, AC-14)")
    assert result.rows == [] and len(result.diagnostics) == 1


def test_duplicate_detected_before_any_execution(db, tmp_path):
    marker = tmp_path / "ran.txt"
    body = f"def run(mart, params):\n    open({str(marker)!r}, 'w').write('x')\n    return []\n"
    a = write_check(tmp_path, "d1", body, check_id="dup")
    b = write_check(tmp_path, "d2", body, check_id="dup")
    result = run(db, [a, b])
    assert any("Duplicate" in d["message"] for d in result.diagnostics), result.diagnostics
    known_defect(marker.exists(), "DISC-09: duplicate CHECK.id detected only after the first check already executed")
