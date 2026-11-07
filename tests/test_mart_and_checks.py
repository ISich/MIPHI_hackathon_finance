"""Stage 3 tests: contract, filters, real supplied checks and isolation."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from decision_diff.check_runner import load_check, run_checks, discover_checks


def test_run_checks_contract_and_overrides(tmp_path: Path) -> None:
    path = tmp_path / "check_example.py"
    path.write_text('''\
def run(mart, params):
    return [{"LABEL":"sample", "SOURCE":"AFTER", "ARGUMENT":"x",
      "CNT":mart.total_apps(), "TOTAL":mart.total_apps(), "METRIC":params["threshold"],
      "APP_IDS":[], "RESULT":"PASS", "CONFIDENCE":"HIGH"}]
CHECK = {"id":"sample", "label":"Sample", "params":{"threshold":1}, "entrypoint":run}
''', encoding="utf-8")
    class FakeMart:
        def total_apps(self) -> int:
            return 12
    results = run_checks(FakeMart(), [path], {"sample": {"threshold": 3}})
    assert not results.diagnostics
    assert results.rows[0]["CNT"] == 12
    assert results.rows[0]["METRIC"] == 3
    assert load_check(path)["id"] == "sample"
    assert discover_checks(tmp_path) == [path]


def test_check_error_is_not_reported_as_pass(tmp_path: Path) -> None:
    path = tmp_path / "check_bad.py"
    path.write_text('def boom(mart, params):\n    raise RuntimeError("oops")\n'
                    'CHECK={"id":"bad", "label":"Bad", "params":{}, "entrypoint":boom}\n', encoding="utf-8")
    result = run_checks(None, [path])
    assert result.rows == []
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0]["error_type"] == "RuntimeError"


def test_mart_filters_and_checks_on_teaching_data(tmp_path: Path) -> None:
    duckdb = pytest.importorskip("duckdb")
    from decision_diff.storage import build_database
    from decision_diff.mart import DuckDBMart, MartFilterError
    from decision_diff.core import normalize_pair
    from decision_diff.configs import REAL
    from decision_diff.segments import build_segment
    from decision_diff.reporting import pivot_facts

    roots = Path(__file__).resolve().parents[1]
    inputs = roots / "examples"
    before = json.loads((inputs / "I32554354_other.json").read_text(encoding="utf-8"))
    after = json.loads((inputs / "I32554354.json").read_text(encoding="utf-8"))
    app_id = "I32554354"
    normalized, comparison = normalize_pair(before, after, app_id, REAL)
    segment = build_segment(before, after, app_id)
    tables = {
        "normalized_union.csv": normalized,
        "comparison.csv": comparison,
        "segments.csv": [segment],
        "pivot_facts.csv": pivot_facts(comparison),
    }
    for name, records in tables.items():
        with (tmp_path / name).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]), delimiter=";")
            writer.writeheader()
            writer.writerows(records)
    db = tmp_path / "mart.duckdb"
    counts = build_database(tmp_path, db)
    assert counts["comparison"] == 141
    assert counts["segments"] == 1
    with DuckDBMart(db) as mart:
        assert mart.total_apps() == 1
        assert mart.count() == 141
        assert mart.count(diff_flag=1) == 25
        assert mart.app_ids(path="decisionResult.decision") == [app_id]
        assert mart.app_ids(path=["decisionResult.decision", "not-present"]) == [app_id]
        assert mart.count(app_ids=[]) == 0
        assert mart.count(change_type=["ATTRIBUTE_NEW", "ATTRIBUTE_LOST"]) == 18
        assert mart.count(path_prefix="decisionResult.") > 0
        assert mart.application(app_id)["segment"]["APP_ID"] == app_id
        assert mart.pivot(limit=2)
        with pytest.raises(MartFilterError):
            mart.rows(sql="DROP TABLE comparison")
        with pytest.raises(MartFilterError):
            mart.count(diff_flag=2)
    with pytest.raises(FileExistsError):
        build_database(tmp_path, db)


def test_all_five_organizer_checks_execute_without_modification() -> None:
    """Contract smoke-test using the real example and a small in-memory adapter."""
    from decision_diff.core import normalize_pair
    from decision_diff.configs import REAL
    from decision_diff.segments import build_segment

    root = Path(__file__).resolve().parents[1]
    before = json.loads((root / "examples/I32554354_other.json").read_text(encoding="utf-8"))
    after = json.loads((root / "examples/I32554354.json").read_text(encoding="utf-8"))
    _, rows = normalize_pair(before, after, "I32554354", REAL)
    segments = [build_segment(before, after, "I32554354")]

    class SimpleMart:
        def rows(self, **filters):
            found = []
            for row in rows:
                if all((row.get(k.upper()) == v if k in ("diff_flag", "change_type", "array_key") else
                        row.get({"path": "PATH", "key": "KEY", "value_before": "VALUE_BEFORE",
                                 "value_after": "VALUE_AFTER"}.get(k, k)) == v)
                       for k, v in filters.items()):
                    found.append(row)
            return found

        def count(self, **filters):
            return len(self.rows(**filters))

        def app_ids(self, **filters):
            return sorted({r["APP_ID"] for r in self.rows(**filters)})

        def segments(self):
            return segments

        def total_apps(self):
            return 1

    checks = discover_checks(root / "checks")
    assert len(checks) == 5
    result = run_checks(SimpleMart(), checks)
    assert not result.diagnostics, result.diagnostics
    assert result.rows
    assert set(item["RESULT"] for item in result.rows) <= {"PASS", "FAIL"}
