"""AC-11 / FR-009: each unchanged organizer check fires FAIL on its own event fixture.

Real path only: JSON -> core CLI -> D4 storage (DuckDB) -> DuckDBMart -> check_runner
-> organizer check file from the pinned commit. No mart double.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from support.fixtures import pair, run_real_pipeline

pytestmark = pytest.mark.contract

def _run_one(db: Path, check_file: Path, overrides=None):
    from decision_diff.check_runner import run_checks
    from decision_diff.mart import DuckDBMart

    with DuckDBMart(db) as mart:
        return run_checks(mart, [check_file], overrides)


def _neutral(n: int = 3):
    return [pair(f"A{i:03d}") for i in range(n)]


@pytest.fixture(scope="module")
def neutral_run(tmp_path_factory):
    return run_real_pipeline(tmp_path_factory.mktemp("neutral"), _neutral())


def test_neutral_fixture_all_five_pass_without_execution_errors(neutral_run, organizer_checks_dir):
    from decision_diff.check_runner import discover_checks, run_checks
    from decision_diff.mart import DuckDBMart

    with DuckDBMart(neutral_run.db) as mart:
        result = run_checks(mart, discover_checks(organizer_checks_dir))
    assert result.diagnostics == []
    assert set(result.timings) == {"ar_drop_by_product", "attribute_new_loss", "external_score_drift",
                                   "stop_factor_disappeared", "target_model_changed"}
    assert {r["RESULT"] for r in result.rows} == {"PASS"}
    assert neutral_run.summary()["changed_apps"] == 0


def test_ar_drop_by_product_fails_on_decision_drop(tmp_path, organizer_checks_dir):
    def to_reject(doc):
        doc["decisionResult"]["decision"] = "REJECT"
    pairs = [pair("B001", to_reject), pair("B002", to_reject), pair("B003")]
    run = run_real_pipeline(tmp_path, pairs)
    result = _run_one(run.db, organizer_checks_dir / "check_ar_drop_by_product.py")
    assert result.diagnostics == []
    (row,) = [r for r in result.rows if r["ARGUMENT"] == "KUPI_KUPI"]
    assert row["RESULT"] == "FAIL"
    assert row["CNT"] == 2 and row["TOTAL"] == 3
    assert row["APP_IDS"] == ["B001", "B002"]
    assert row["CONFIDENCE"] == "LOW"  # 2 < low_confidence_cnt=5, verdict kept as FAIL


def test_ar_drop_by_product_params_are_applied(tmp_path, organizer_checks_dir):
    def to_reject(doc):
        doc["decisionResult"]["decision"] = "REJECT"
    run = run_real_pipeline(tmp_path, [pair("B001", to_reject), pair("B002"), pair("B003")])
    loose = _run_one(run.db, organizer_checks_dir / "check_ar_drop_by_product.py",
                     {"ar_drop_by_product": {"max_drop_rel": 0.9, "app_ids_limit": 0}})
    (row,) = loose.rows
    assert row["RESULT"] == "PASS" and row["CNT"] == 1 and row["APP_IDS"] == []


def test_attribute_new_loss_fails_on_new_and_lost_path(tmp_path, organizer_checks_dir):
    def add_and_drop(doc):
        doc["characteristics"]["score_new"] = 1
        del doc["characteristics"]["score_equ"]
    run = run_real_pipeline(tmp_path, [pair("C001", add_and_drop), pair("C002")])
    result = _run_one(run.db, organizer_checks_dir / "check_attribute_new_loss.py")
    assert result.diagnostics == []
    by_arg = {r["ARGUMENT"]: r for r in result.rows}
    assert by_arg["characteristics.score_new"]["RESULT"] == "FAIL"
    assert by_arg["characteristics.score_new"]["SOURCE"] == "AFTER"
    assert by_arg["characteristics.score_equ"]["SOURCE"] == "BEFORE"
    assert by_arg["characteristics.score_equ"]["APP_IDS"] == ["C001"]


def test_external_score_drift_fails_on_score_change_with_decision_change(tmp_path, organizer_checks_dir):
    def drift(doc):
        doc["characteristics"]["score_okb"] = 500
        doc["decisionResult"]["decision"] = "REJECT"
    run = run_real_pipeline(tmp_path, [pair("D001", drift), pair("D002")])
    result = _run_one(run.db, organizer_checks_dir / "check_external_score_drift.py")
    assert result.diagnostics == []
    (row,) = [r for r in result.rows if r["ARGUMENT"] == "characteristics.score_okb"]
    assert row["RESULT"] == "FAIL" and row["APP_IDS"] == ["D001"]


def test_external_score_drift_predictor_mismatch(tmp_path, organizer_checks_dir):
    def drift_feature_only(doc):
        doc["characteristics"]["score_okb"] = 600  # feature stays 710 -> mismatch
    run = run_real_pipeline(tmp_path, [pair("E001", drift_feature_only, feature_score_okb=710),
                                       pair("E002", feature_score_okb=710)])
    result = _run_one(run.db, organizer_checks_dir / "check_external_score_drift.py")
    assert result.diagnostics == []
    (row,) = [r for r in result.rows if r["ARGUMENT"] == "предиктор != источник"]
    assert row["RESULT"] == "FAIL" and row["APP_IDS"] == ["E001"]


def test_stop_factor_disappeared_fails_on_hit_true_to_false_and_lost_rule(tmp_path, organizer_checks_dir):
    def turned_off(doc):
        doc["decisionResult"]["product_trials"][0]["rules"][1]["hit"] = False

    def removed(doc):
        doc["decisionResult"]["product_trials"][0]["rules"].pop(1)
    rules = [("RESTRICTED_REGIONS", False), ("AGELOW@21", True)]
    run = run_real_pipeline(tmp_path, [pair("F001", turned_off, rules=rules),
                                       pair("F002", removed, rules=rules),
                                       pair("F003", rules=rules)])
    result = _run_one(run.db, organizer_checks_dir / "check_stop_factor_disappeared.py")
    assert result.diagnostics == []
    fails = [r for r in result.rows if r["RESULT"] == "FAIL"]
    assert {tuple(r["APP_IDS"]) for r in fails} == {("F001",), ("F002",)}
    assert {r["ARGUMENT"] for r in fails} == {"AGELOW@21"}  # ARRAY_KEY "<product_id>|<rule>" parsed


def test_target_model_changed_fails_on_pd_model_switch(tmp_path, organizer_checks_dir):
    def switch(doc):
        trial = doc["decisionResult"]["product_trials"][0]
        trial["scoring"]["pd"]["modelName"] = "ML_V2"
    run = run_real_pipeline(tmp_path, [pair("G001", switch), pair("G002")])
    result = _run_one(run.db, organizer_checks_dir / "check_target_model_changed.py")
    assert result.diagnostics == []
    (row,) = result.rows
    assert row["RESULT"] == "FAIL" and row["ARGUMENT"] == "ML_MICRO_LOAN_V1 -> ML_V2"
    assert row["APP_IDS"] == ["G001"]


def test_rows_satisfy_organizer_row_contract(neutral_run, organizer_checks_dir):
    from decision_diff.check_runner import REQUIRED_FIELDS, discover_checks, run_checks
    from decision_diff.mart import DuckDBMart

    with DuckDBMart(neutral_run.db) as mart:
        result = run_checks(mart, discover_checks(organizer_checks_dir))
    for row in result.rows:
        assert REQUIRED_FIELDS <= row.keys()
        assert row["SOURCE"] in ("BEFORE", "AFTER")
        assert row["RESULT"] in ("PASS", "FAIL")
        assert row["CONFIDENCE"] in ("HIGH", "LOW")
        assert isinstance(row["CNT"], int) and isinstance(row["TOTAL"], int)
        assert row["APP_IDS"] == sorted(set(row["APP_IDS"]))


def test_organizer_check_sources_unchanged_from_pinned_commit(organizer_checks_dir):
    """Checks run by this suite are byte-identical to the pinned commit ("без изменения исходников")."""
    import os
    import subprocess

    root = Path(__file__).resolve().parents[2]
    sha = os.environ.get("CORE_SHA", (root / "CORE_COMMIT").read_text().strip())
    for path in sorted(organizer_checks_dir.glob("check_*.py")):
        pinned = subprocess.run(["git", "-C", str(root), "show", f"{sha}:checks/{path.name}"],
                                capture_output=True, check=True).stdout
        assert hashlib.sha256(path.read_bytes()).hexdigest() == hashlib.sha256(pinned).hexdigest(), path.name
