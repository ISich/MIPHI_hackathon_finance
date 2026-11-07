"""MartAPI (D4 `DuckDBMart` @ pinned core) against PRD §8.3 / S5 and docs/contracts/data.md.

Real DuckDB built by the real core CLI + D4 storage. A documented discrepancy (DISC-xx)
is an expected failure ONLY under its exact defect condition (support.http_api.known_defect);
any other failure is a real FAIL, and a fixed defect makes the test run its real assertions.
"""
from __future__ import annotations

import csv
import random

import pytest

from support.fixtures import pair, run_real_pipeline
from support.http_api import known_defect

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
    assert len(keys) == len(set(keys)) and keys
    known_defect(keys != sorted(keys), "DISC-01: rows() has no ORDER BY; PRD §8.3 fixes (APP_ID, PATH, ARRAY_KEY)")


@pytest.mark.parametrize("name", ["key", "array_key", "value_before"])
def test_list_for_scalar_filter_is_mart_filter_error(mart, name):
    import duckdb

    from decision_diff.mart import MartFilterError

    try:
        mart.count(**{name: ["x"]})
    except MartFilterError:
        return
    except duckdb.ConversionException:
        known_defect(True, "DISC-02: list in scalar filter raises raw duckdb.ConversionException, not MartFilterError")
    pytest.fail(f"list for scalar filter {name!r} was silently accepted")


def drilldown_page(result):
    """ONE response contract for both drill-down tests (CR2 #1).

    Target (data.md): mapping with ``items`` (APP_ID page) and ``total`` (full distinct count).
    Pinned D4 today: a plain list (page only) -> (items, None). Anything else is a contract error.
    """
    if isinstance(result, dict):
        assert set(result) >= {"items", "total"}, result
        assert isinstance(result["items"], list) and isinstance(result["total"], int), result
        return [str(x) for x in result["items"]], result["total"]
    assert isinstance(result, list), type(result)
    return [str(x) for x in result], None


def _expected_members(mart, fact):
    """Independent membership from comparison rows: same group, the fact's side present."""
    side = "ADJUSTED_BEFORE" if fact["SOURCE"] == "BEFORE" else "ADJUSTED_AFTER"
    absent = "ATTRIBUTE_NEW" if fact["SOURCE"] == "BEFORE" else "ATTRIBUTE_LOST"
    return sorted({r["APP_ID"] for r in mart.rows(path=fact["PATH"], array_key=fact["ARRAY_KEY"],
                                                  diff_flag=int(fact["DIFF_FLAG"]))
                   if r[side] == fact["VALUE_ADJUSTED"] and r["CHANGE_TYPE"] != absent})


@pytest.fixture()
def rollup(run, tmp_path):
    """D4 data.md port (core >= 421da26): BaseFacts/BaseMembership + server rollup on a private writable copy."""
    import shutil

    import duckdb

    from decision_diff.base_facts import materialize_base_facts
    from decision_diff.pivot_rollup import PivotRollup

    db = tmp_path / "mart.duckdb"
    shutil.copy(run.db, db)
    con = duckdb.connect(str(db))
    materialize_base_facts(con)
    yield PivotRollup(con, run_id="run_qa", data_revision="rev_qa", signing_secret=b"qa-secret"), con
    con.close()


def test_pivot_drilldown_returns_full_distinct_total(rollup, mart):
    """data.md level 2 (was DISC-03 against the legacy DuckDBMart.pivot_app_ids page): members() returns a page
    plus the FULL distinct total, equal to the independently computed APP_ID set; out-of-range keeps the total."""
    pivot, _ = rollup
    cells = pivot.cells(dimensions=["PATH"], filters={"PATH": SCORE})["items"]
    assert len(cells) == 1
    expected = sorted({r["APP_ID"] for r in mart.rows(path=SCORE)})
    assert cells[0]["cnt"] == len(expected) == 4
    page = pivot.members(cells[0]["group_locator"], limit=1)
    assert page["total"] == 4 and len(page["items"]) == 1
    assert pivot.members(cells[0]["group_locator"], limit=50)["items"] == expected
    beyond = pivot.members(cells[0]["group_locator"], limit=1, offset=10)
    assert beyond["items"] == [] and beyond["total"] == 4


def test_pivot_drilldown_matches_fact_cnt(mart):
    """AC-09: drill-down membership of a base fact == independently computed APP_ID set, and its size == CNT."""
    facts = [f for f in mart.pivot(limit=100000) if f["PATH"] == SCORE]
    assert facts
    for fact in facts:
        group = {k: fact[k] for k in ("PATH", "ARRAY_KEY", "VALUE_ADJUSTED", "DIFF_FLAG", "SOURCE")}
        items, total = drilldown_page(mart.pivot_app_ids(group, limit=10000))
        expected = _expected_members(mart, fact)
        assert sorted(items) == expected and len(expected) == fact["CNT"], (fact, items, expected)
        if total is not None:
            assert total == fact["CNT"]


def test_base_facts_have_change_type_dimension(rollup, mart):
    """data.md level 1 (was DISC-04 against legacy pivot_facts): BaseFacts carry CHANGE_TYPE (and segment
    dimensions), CNT == |BaseMembership| per fact, and a CHANGE_TYPE cell matches comparison rows."""
    pivot, con = rollup
    columns = {r[0] for r in con.execute("DESCRIBE base_facts").fetchall()}
    assert {"CHANGE_TYPE", "SOURCE", "DIFF_FLAG", "PATH", "DECISION_CHANGED", "CNT"} <= columns
    bad = con.execute("SELECT COUNT(*) FROM base_facts f JOIN (SELECT fact_id, COUNT(DISTINCT APP_ID) n "
                      "FROM base_membership GROUP BY fact_id) m USING (fact_id) WHERE f.CNT <> m.n").fetchone()[0]
    assert bad == 0
    lost = pivot.cells(dimensions=["CHANGE_TYPE"], filters={"CHANGE_TYPE": "ATTRIBUTE_LOST"})["items"]
    assert [c["cnt"] for c in lost] == [len(mart.app_ids(change_type="ATTRIBUTE_LOST"))]
