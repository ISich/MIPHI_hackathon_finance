"""MartAPI (D4 `DuckDBMart` @ pinned core) against PRD §8.3 / S5 and docs/contracts/data.md.

Real DuckDB built by the real core CLI + D4 storage. `xfail(strict)` = a documented
discrepancy (DISC-xx in QA_RESULT.md); it turns red when D4 fixes it, so the marker
must then be removed.
"""
from __future__ import annotations

import csv
import random

import pytest

from support.fixtures import pair, run_real_pipeline

pytestmark = pytest.mark.contract

SCORE = "characteristics.score_okb"


def _changed(doc):
    doc["characteristics"]["score_okb"] = 1
    doc["characteristics"]["empty_new"] = ""
    del doc["characteristics"]["score_equ"]
    doc["decisionResult"]["product_trials"][0]["rules"][0]["hit"] = None


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    pairs = [pair("M2", _changed), pair("M1"), pair("M10", _changed), pair("M3")]
    return run_real_pipeline(tmp_path_factory.mktemp("mart"), pairs)


@pytest.fixture()
def mart(run):
    from decision_diff.mart import DuckDBMart

    with DuckDBMart(run.db) as m:
        yield m


def test_five_methods_exist(mart):
    for name in ("rows", "count", "app_ids", "segments", "total_apps"):
        assert callable(getattr(mart, name))


def test_total_apps_and_segments_one_row_per_app(mart):
    segs = list(mart.segments())
    assert mart.total_apps() == 4 == len(segs) == len({s["APP_ID"] for s in segs})


def test_count_is_rows_not_distinct_apps(mart):
    filters = {"diff_flag": 1}
    assert mart.count(**filters) == len(list(mart.rows(**filters)))
    assert mart.count(**filters) > len(mart.app_ids(**filters))


def test_app_ids_sorted_unique_and_consistent_with_rows(mart):
    for filters in ({}, {"diff_flag": 1}, {"change_type": "ATTRIBUTE_LOST"}, {"path_prefix": "characteristics."}):
        ids = mart.app_ids(**filters)
        assert ids == sorted(set(ids))
        assert set(ids) == {r["APP_ID"] for r in mart.rows(**filters)}


@pytest.mark.parametrize("filters, expected_apps", [
    ({"path": SCORE}, ["M1", "M10", "M2", "M3"]),
    ({"path": [SCORE, "no.such.path"]}, ["M1", "M10", "M2", "M3"]),
    ({"path": SCORE, "diff_flag": 1}, ["M10", "M2"]),
    ({"path": SCORE, "diff_flag": 0}, ["M1", "M3"]),
    ({"path_prefix": "characteristics.score_"}, ["M1", "M10", "M2", "M3"]),
    ({"key": "score_equ", "change_type": "ATTRIBUTE_LOST"}, ["M10", "M2"]),
    ({"change_type": ["ATTRIBUTE_NEW", "ATTRIBUTE_LOST"]}, ["M10", "M2"]),
    ({"value_before": "710", "value_after": "1"}, ["M10", "M2"]),
    ({"app_ids": ["M2"], "diff_flag": 1}, ["M2"]),
    ({"app_ids": "M3", "path": SCORE}, ["M3"]),
])
def test_s5_filters_are_and_combined(mart, filters, expected_apps):
    assert mart.app_ids(**filters) == expected_apps


@pytest.mark.parametrize("name", ["path", "change_type", "app_ids"])
def test_empty_list_filter_gives_empty_set(mart, name):
    assert mart.count(**{name: []}) == 0
    assert mart.app_ids(**{name: []}) == []


def test_array_key_is_full_array_key(mart):
    rows = list(mart.rows(path="decisionResult.product_trials.rules.hit", app_ids=["M1"]))
    assert {r["ARRAY_KEY"] for r in rows} == {"15210|RESTRICTED_REGIONS", "15210|AGELOW@21"}
    assert mart.count(array_key="15210|AGELOW@21", path="decisionResult.product_trials.rules.hit") == 4
    assert mart.count(array_key="AGELOW@21") == 0


def test_unknown_filter_is_error_not_ignored(mart):
    from decision_diff.mart import MartFilterError

    with pytest.raises(MartFilterError):
        mart.rows(pth=SCORE)
    with pytest.raises(MartFilterError):
        mart.count(diff_flag=2)


def test_missing_vs_null_vs_empty_string(mart):
    """data.md: missing side is "" ; JSON null is "NULL"; presence is told by CHANGE_TYPE."""
    hit = {r["ARRAY_KEY"]: r for r in mart.rows(path="decisionResult.product_trials.rules.hit", app_ids=["M2"])}
    assert hit["15210|RESTRICTED_REGIONS"]["VALUE_AFTER"] == "NULL"
    assert hit["15210|RESTRICTED_REGIONS"]["CHANGE_TYPE"] == "VALUE_CHANGED"
    (lost,) = mart.rows(path="characteristics.score_equ", app_ids=["M2"])
    assert lost["VALUE_AFTER"] == "" and lost["CHANGE_TYPE"] == "ATTRIBUTE_LOST"
    (new_empty,) = mart.rows(path="characteristics.empty_new", app_ids=["M2"])
    assert new_empty["VALUE_AFTER"] == "" and new_empty["CHANGE_TYPE"] == "ATTRIBUTE_NEW"


def test_types_survive_storage_roundtrip(mart):
    """data.md: no 0 -> "0" / true -> True conversion; DIFF_FLAG / DECISION_CHANGED are ints."""
    (row,) = mart.rows(path=SCORE, app_ids=["M1"])
    assert row["VALUE_BEFORE"] == "710" and isinstance(row["DIFF_FLAG"], int)
    (seg,) = [s for s in mart.segments() if s["APP_ID"] == "M1"]
    assert seg["DECISION_CHANGED"] == 0 and isinstance(seg["DECISION_CHANGED"], int)
    rules = {r["ARRAY_KEY"]: r["VALUE_BEFORE"] for r in mart.rows(path="decisionResult.product_trials.rules.hit",
                                                                  app_ids=["M1"])}
    assert set(rules.values()) == {"false"}


def test_diff_flag_zero_only_for_same(mart):
    rows = list(mart.rows())
    assert all((r["DIFF_FLAG"] == 0) == (r["CHANGE_TYPE"] == "SAME") for r in rows)
    assert {r["CHANGE_TYPE"] for r in rows} <= {"SAME", "VALUE_CHANGED", "ATTRIBUTE_NEW", "ATTRIBUTE_LOST"}


def test_mart_is_read_only(mart):
    with pytest.raises(Exception):
        mart._connection.execute("DELETE FROM comparison")


@pytest.mark.xfail(reason="DISC-01: rows() has no ORDER BY; PRD §8.3 fixes order (APP_ID, PATH, ARRAY_KEY). "
                          "Holds today only because the CLI writes sorted CSV.")
def test_rows_order_is_fixed_even_if_storage_input_unsorted(run, tmp_path):
    from decision_diff.mart import DuckDBMart
    from decision_diff.storage import build_database

    src = run.out
    out = tmp_path / "shuffled"
    out.mkdir()
    for name in ("comparison.csv", "segments.csv", "pivot_facts.csv", "normalized_union.csv"):
        rows = list(csv.DictReader((src / name).open(encoding="utf-8-sig"), delimiter=";"))
        random.Random(7).shuffle(rows)
        with (out / name).open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter=";")
            w.writeheader()
            w.writerows(rows)
    build_database(out, out / "mart.duckdb")
    with DuckDBMart(out / "mart.duckdb") as m:
        keys = [(r["APP_ID"], r["PATH"], r["ARRAY_KEY"]) for r in m.rows()]
    assert keys == sorted(keys)


@pytest.mark.xfail(reason="DISC-02: list passed to scalar filter (key/array_key/value_*) raises raw DuckDB "
                          "ConversionException, not a MartFilterError diagnostic (PRD §8.3 A: diagnostic error).")
@pytest.mark.parametrize("name", ["key", "array_key", "value_before"])
def test_list_for_scalar_filter_is_mart_filter_error(mart, name):
    from decision_diff.mart import MartFilterError

    with pytest.raises(MartFilterError):
        mart.count(**{name: ["x"]})


@pytest.mark.xfail(reason="DISC-03: pivot_app_ids returns a capped list (limit<=10000) without full distinct "
                          "total/pagination; data.md requires items + full distinct total.")
def test_pivot_drilldown_returns_full_distinct_total(mart):
    result = mart.pivot_app_ids({"SOURCE": "BEFORE", "PATH": SCORE}, limit=1)
    assert isinstance(result, dict) and result.get("total") == 4


def test_pivot_drilldown_matches_fact_cnt(mart):
    """CNT of a base fact == distinct APP_IDs from drill-down (AC-09, single fact)."""
    facts = [f for f in mart.pivot(limit=100000) if f["PATH"] == SCORE]
    assert facts
    for fact in facts:
        group = {k: fact[k] for k in ("PATH", "ARRAY_KEY", "VALUE_ADJUSTED", "DIFF_FLAG", "SOURCE")}
        assert len(mart.pivot_app_ids(group, limit=10000)) == fact["CNT"]


@pytest.mark.xfail(reason="DISC-04: pivot_facts has no CHANGE_TYPE / segments dimensions and no materialized "
                          "BaseMembership (data.md level 1); known per core-verification.md.")
def test_base_facts_have_change_type_dimension(mart):
    fact = mart.pivot(limit=1)[0]
    assert "CHANGE_TYPE" in fact
