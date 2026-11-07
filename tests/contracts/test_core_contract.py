"""Core D1 (pinned) vs PRD AC-02..AC-06, AC-08 and FR-019..021, via public functions and the real CLI."""
from __future__ import annotations

import dataclasses
import json

import pytest

from support.fixtures import base_doc, pair, run_cli, write_dataset

pytestmark = pytest.mark.contract


def _cmp(before, after, config=None):
    from decision_diff.configs import REAL
    from decision_diff.core import normalize_pair

    _, rows = normalize_pair(before, after, "X1", config or REAL)
    return {(r["PATH"], r["ARRAY_KEY"]): r for r in rows}


def test_ac03_four_change_types_and_one_row_per_key():
    _, before, after = pair("X1")
    after["characteristics"]["score_okb"] = 1           # VALUE_CHANGED
    after["characteristics"]["brand_new"] = "y"         # ATTRIBUTE_NEW
    del after["characteristics"]["score_equ"]           # ATTRIBUTE_LOST
    rows = _cmp(before, after)
    assert rows[("characteristics.score_okb", "")]["CHANGE_TYPE"] == "VALUE_CHANGED"
    assert rows[("characteristics.brand_new", "")]["CHANGE_TYPE"] == "ATTRIBUTE_NEW"
    assert rows[("characteristics.score_equ", "")]["CHANGE_TYPE"] == "ATTRIBUTE_LOST"
    assert rows[("decisionResult.decision", "")]["CHANGE_TYPE"] == "SAME"
    assert all(r["DIFF_FLAG"] == int(r["CHANGE_TYPE"] != "SAME") for r in rows.values())


def test_ac04_exclusions_on_and_off():
    _, before, after = pair("X1")
    after["appData"]["request_id"] = "other"
    after["appData"]["createDateTime"] = "2030-01-01T00:00:00Z"
    on = _cmp(before, after)
    assert not any(p.startswith("appData.request_id") or p.startswith("appData.createDateTime") for p, _ in on)
    assert all(r["DIFF_FLAG"] == 0 for r in on.values())
    from decision_diff.configs import REAL

    off = _cmp(before, after, dataclasses.replace(REAL, excluded_paths=frozenset()))
    assert off[("appData.request_id", "")]["CHANGE_TYPE"] == "VALUE_CHANGED"
    assert off[("appData.createDateTime", "")]["CHANGE_TYPE"] == "VALUE_CHANGED"


def test_ac05_key_array_reorder_no_false_diff_and_composite_keys():
    before = base_doc("X1")
    before["product_catalog"].append({"is_new_mfo": True, "mfo_id": "MFO_B", "product_id": 15210,
                                      "routing_method": "direct"})
    after = json.loads(json.dumps(before))
    after["product_catalog"].reverse()
    rows = _cmp(before, after)
    assert all(r["DIFF_FLAG"] == 0 for r in rows.values())
    keys = {ak for (p, ak) in rows if p == "product_catalog.routing_method"}
    assert keys == {"MFO_A:15210", "MFO_B:15210"}  # composite key not glued into one


def test_ac05_positional_vector_order_matters():
    before = base_doc("X1")
    after = json.loads(json.dumps(before))
    after["decisionResult"]["scoring"][0]["value"].reverse()
    rows = _cmp(before, after)
    changed = [k for k, r in rows.items() if r["DIFF_FLAG"] and k[0] == "decisionResult.scoring.value"]
    assert len(changed) == 2


def test_ac05_two_models_with_same_feature_kept_apart():
    before = base_doc("X1", feature_score_okb=700)
    second = json.loads(json.dumps(before["decisionResult"]["scoring"][0]))
    second["modelName"] = "OTHER_MODEL"
    before["decisionResult"]["scoring"].append(second)
    after = json.loads(json.dumps(before))
    after["decisionResult"]["scoring"][1]["features"]["score_okb"] = 1
    rows = _cmp(before, after)
    feat = {ak: r["CHANGE_TYPE"] for (p, ak), r in rows.items() if p == "decisionResult.scoring.features.score_okb"}
    assert feat == {"ML_MICRO_LOAN_V1": "SAME", "OTHER_MODEL": "VALUE_CHANGED"}


def test_ac06_null_false_empty_missing_are_distinct():
    _, before, after = pair("X1")
    before["characteristics"].update({"a": None, "b": False, "c": ""})
    after["characteristics"].update({"a": False, "b": "", "c": None})
    rows = _cmp(before, after)
    assert rows[("characteristics.a", "")]["VALUE_BEFORE"] == "NULL"
    assert {rows[("characteristics." + k, "")]["CHANGE_TYPE"] for k in "abc"} == {"VALUE_CHANGED"}


def test_ac06_value_change_inside_bucket_is_not_lost():
    from decision_diff.core import NormalizationConfig, normalize_pair

    cfg = NormalizationConfig(arrays={}, buckets={"s": ((0.5, "low"), (1.0, "high"))})
    _, rows = normalize_pair({"s": 0.42}, {"s": 0.48}, "X1", cfg)
    (row,) = rows
    assert row["ADJUSTED_BEFORE"] == row["ADJUSTED_AFTER"] == "low"
    assert row["CHANGE_TYPE"] == "VALUE_CHANGED" and row["DIFF_FLAG"] == 1


def test_ac06_int_vs_string_policy_is_observable():
    """Q5 pending: today 1 and "1" are SAME (both stringify to "1"). Recorded as an observation (OBS-01)."""
    rows = _cmp({"characteristics": {"n": 1}}, {"characteristics": {"n": "1"}})
    assert rows[("characteristics.n", "")]["CHANGE_TYPE"] == "SAME"


def test_ac08_decision_changed_from_decision_result_not_offers():
    from decision_diff.segments import build_segment

    _, before, after = pair("X1")
    after["decisionResult"]["available_offers"] = []      # offers change, decision stays
    after["decisionResult"]["product_trials"][0]["decision"] = "REJECT"
    seg = build_segment(before, after, "X1")
    assert seg["DECISION_BEFORE"] == seg["DECISION_AFTER"] == "APPROVE" and seg["DECISION_CHANGED"] == 0
    after["decisionResult"]["decision"] = "REJECT"
    assert build_segment(before, after, "X1")["DECISION_CHANGED"] == 1


def test_unconfigured_array_and_duplicate_identity_fail_loudly():
    from decision_diff.core import NormalizationError

    _, before, after = pair("X1")
    after["unknown_list"] = [1, 2]
    with pytest.raises(NormalizationError):
        _cmp(before, after)
    _, before, after = pair("X1")
    after["product_catalog"].append(dict(after["product_catalog"][0]))
    with pytest.raises(NormalizationError):
        _cmp(before, after)


def test_ac02_cli_reports_missing_pair_and_invalid_json_in_issues(tmp_path):
    """Library/CLI layer: problems land in issues.json. The CLI still exits 0 and writes outputs
    for the remaining pairs (OBS-02) - the FAILED policy of AC-02 must be enforced by D2 runner."""
    before_dir, after_dir = write_dataset(tmp_path / "d", [pair("P1"), pair("P2"), pair("P3")])
    (after_dir / "P2.json").unlink()
    (after_dir / "P3.json").write_text("{not json", encoding="utf-8")
    proc = run_cli(before_dir, after_dir, tmp_path / "out")
    issues = json.loads((tmp_path / "out" / "issues.json").read_text(encoding="utf-8"))
    assert issues["missing_after"] == ["P2.json"]
    assert [f["file"] for f in issues["failed"]] == ["P3.json"]
    assert proc.returncode == 0
    assert json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))["total_apps"] == 1
