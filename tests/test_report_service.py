"""D4 report-service contract tests; one integration test needs DuckDB."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from decision_diff.report_service import ReportQueryError, build_group_where


def test_group_where_requires_source_and_validates_columns() -> None:
    with pytest.raises(ReportQueryError):
        build_group_where({"PATH": "decisionResult.decision"})
    with pytest.raises(ReportQueryError):
        build_group_where({"SOURCE": "AFTER", "SQL": "x"})
    where, params = build_group_where({"SOURCE": "AFTER", "PATH": "decisionResult.decision", "DIFF_FLAG": 1})
    assert '"PATH" = ?' in where
    assert params == ["ATTRIBUTE_LOST", "decisionResult.decision", 1]


def test_group_where_uses_correct_adjusted_slice() -> None:
    where, params = build_group_where({"SOURCE": "BEFORE", "VALUE_ADJUSTED": "(0 - 0.3]"})
    assert '"ADJUSTED_BEFORE" = ?' in where
    assert params == ["ATTRIBUTE_NEW", "(0 - 0.3]"]
    with pytest.raises(ReportQueryError):
        build_group_where({"SOURCE": "AFTER", "DIFF_FLAG": 9})


def test_report_service_real_pair(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    from decision_diff.core import normalize_pair
    from decision_diff.configs import REAL
    from decision_diff.segments import build_segment
    from decision_diff.reporting import pivot_facts
    from decision_diff.storage import build_database
    from decision_diff.report_service import ReportService

    root = Path(__file__).resolve().parents[1]
    examples = root / "examples"
    before = json.loads((examples / "I32554354_other.json").read_text(encoding="utf-8"))
    after = json.loads((examples / "I32554354.json").read_text(encoding="utf-8"))
    app_id = "I32554354"
    union, comparison = normalize_pair(before, after, app_id, REAL)
    tables = {
        "normalized_union.csv": union,
        "comparison.csv": comparison,
        "segments.csv": [build_segment(before, after, app_id)],
        "pivot_facts.csv": pivot_facts(comparison),
    }
    for name, rows in tables.items():
        with (tmp_path / name).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter=";")
            writer.writeheader()
            writer.writerows(rows)
    db = tmp_path / "mart.duckdb"
    build_database(tmp_path, db)
    with ReportService(db) as service:
        assert service.summary()["total_apps"] == 1
        assert service.summary()["changed_apps"] == 1
        assert service.top_changed_paths(limit=5)
        group = {"SOURCE": "AFTER", "PATH": "decisionResult.decision"}
        members = service.group_members(group)
        assert members["total"] == 1
        assert members["items"] == [app_id]
        assert service.group_members(group, offset=1)["items"] == []
        assert service.application(app_id, changed_only=True)["attributes"]
        assert service.pivot_facts(limit=5)["total"] > 0
        assert service.validate_memberships(sample_limit=20)["ok"]
        with pytest.raises(KeyError):
            service.application("unknown")
