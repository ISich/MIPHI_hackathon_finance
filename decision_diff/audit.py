"""Read-only integrity audit for completed D1/D4 run artifacts.

The audit does not change the normalizer, DuckDB schema, or checks. All counts
are computed from the run under inspection: no hidden/reference answers.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .pivot_rollup import PivotQueryError, PivotRollup


class AuditFailure(RuntimeError):
    """Audit cannot complete because required input data are unavailable."""


def _scalar(connection: Any, query: str) -> int:
    return int(connection.execute(query).fetchone()[0])


def _check_record(name: str, actual: Any, expected: Any, *, details: str = "") -> dict[str, Any]:
    result = {"name": name, "ok": actual == expected, "actual": actual, "expected": expected}
    if details:
        result["details"] = details
    return result


def audit_database(connection: Any, *, sample_limit: int = 30) -> list[dict[str, Any]]:
    """Audit DB consistency without writing to it.

    This is intentionally independent of the fixed 2002-app public dataset.
    It remains valid for new runs with different sizes and new attributes.
    """
    if type(sample_limit) is not int or not 1 <= sample_limit <= 100:
        raise ValueError("sample_limit must be an integer between 1 and 100")
    required = {"normalized_union", "comparison", "segments", "base_facts", "base_membership"}
    tables = {row[0] for row in connection.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()}
    missing = sorted(required - tables)
    if missing:
        raise AuditFailure(f"Required DuckDB tables missing: {missing}")

    checks: list[dict[str, Any]] = []
    run = lambda name, actual, expected, details="": checks.append(_check_record(name, actual, expected, details=details))
    normalized_count = _scalar(connection, 'SELECT COUNT(*) FROM normalized_union')
    comparison_count = _scalar(connection, 'SELECT COUNT(*) FROM comparison')
    segment_count = _scalar(connection, 'SELECT COUNT(*) FROM segments')
    membership_count = _scalar(connection, 'SELECT COUNT(*) FROM base_membership')
    fact_count = _scalar(connection, 'SELECT COUNT(*) FROM base_facts')

    run("segments_unique_app_ids", segment_count,
        _scalar(connection, 'SELECT COUNT(DISTINCT APP_ID) FROM segments'))
    run("comparison_unique_identity", comparison_count,
        _scalar(connection, 'SELECT COUNT(DISTINCT (APP_ID, PATH, ARRAY_KEY)) FROM comparison'))
    run("normalized_unique_identity", normalized_count,
        _scalar(connection, 'SELECT COUNT(DISTINCT (APP_ID, SOURCE, PATH, ARRAY_KEY)) FROM normalized_union'))
    run("normalized_valid_sources", _scalar(connection,
        "SELECT COUNT(*) FROM normalized_union WHERE SOURCE NOT IN ('BEFORE','AFTER') OR SOURCE IS NULL"), 0)
    run("comparison_valid_statuses", _scalar(connection,
        """SELECT COUNT(*) FROM comparison WHERE
           CHANGE_TYPE NOT IN ('SAME','VALUE_CHANGED','ATTRIBUTE_NEW','ATTRIBUTE_LOST')
           OR CHANGE_TYPE IS NULL OR DIFF_FLAG NOT IN (0,1) OR DIFF_FLAG IS NULL
           OR (CHANGE_TYPE = 'SAME' AND DIFF_FLAG <> 0)
           OR (CHANGE_TYPE <> 'SAME' AND DIFF_FLAG <> 1)"""), 0)
    run("segment_decisions_consistent", _scalar(connection,
        """SELECT COUNT(*) FROM segments WHERE DECISION_CHANGED <> CASE
           WHEN DECISION_BEFORE IS DISTINCT FROM DECISION_AFTER THEN 1 ELSE 0 END
           OR DECISION_CHANGED IS NULL"""), 0)
    run("normalized_rows_mapped_to_comparison", _scalar(connection,
        """SELECT COUNT(*) FROM normalized_union n LEFT JOIN comparison c
           ON n.APP_ID=c.APP_ID AND n.PATH=c.PATH AND n.ARRAY_KEY=c.ARRAY_KEY
           WHERE c.APP_ID IS NULL"""), 0)
    run("comparison_has_normalized_row", _scalar(connection,
        """SELECT COUNT(*) FROM comparison c LEFT JOIN normalized_union n
           ON n.APP_ID=c.APP_ID AND n.PATH=c.PATH AND n.ARRAY_KEY=c.ARRAY_KEY
           WHERE n.APP_ID IS NULL"""), 0)
    run("segments_cover_normalized_apps", _scalar(connection,
        """SELECT COUNT(*) FROM (SELECT DISTINCT APP_ID FROM normalized_union) n
           LEFT JOIN segments s USING (APP_ID) WHERE s.APP_ID IS NULL"""), 0)
    run("change_type_matches_actual_values", _scalar(connection,
        """SELECT COUNT(*) FROM comparison c
           LEFT JOIN normalized_union b ON b.APP_ID=c.APP_ID AND b.PATH=c.PATH
                 AND b.ARRAY_KEY=c.ARRAY_KEY AND b.SOURCE='BEFORE'
           LEFT JOIN normalized_union a ON a.APP_ID=c.APP_ID AND a.PATH=c.PATH
                 AND a.ARRAY_KEY=c.ARRAY_KEY AND a.SOURCE='AFTER'
           WHERE c.CHANGE_TYPE <> CASE
               WHEN b.APP_ID IS NULL THEN 'ATTRIBUTE_NEW'
               WHEN a.APP_ID IS NULL THEN 'ATTRIBUTE_LOST'
               WHEN b.VALUE IS DISTINCT FROM a.VALUE THEN 'VALUE_CHANGED'
               ELSE 'SAME' END"""), 0,
        "Classification uses source-row presence; JSON null is distinct from missing attribute")
    run("base_membership_unique_pair", membership_count,
        _scalar(connection, 'SELECT COUNT(DISTINCT (fact_id, APP_ID)) FROM base_membership'))
    run("base_fact_unique_id", fact_count,
        _scalar(connection, 'SELECT COUNT(DISTINCT fact_id) FROM base_facts'))
    run("membership_references_fact", _scalar(connection,
        """SELECT COUNT(*) FROM base_membership m LEFT JOIN base_facts f
           ON m.fact_id=f.fact_id WHERE f.fact_id IS NULL"""), 0)
    run("membership_app_exists", _scalar(connection,
        """SELECT COUNT(*) FROM base_membership m LEFT JOIN segments s
           ON m.APP_ID=s.APP_ID WHERE s.APP_ID IS NULL"""), 0)
    run("base_facts_cnt_matches_membership", _scalar(connection,
        """SELECT COUNT(*) FROM base_facts f LEFT JOIN (
             SELECT fact_id, COUNT(DISTINCT APP_ID) cnt FROM base_membership GROUP BY fact_id
           ) m ON f.fact_id=m.fact_id WHERE f.CNT IS DISTINCT FROM m.cnt"""), 0)
    run("membership_matches_normalized_count", membership_count, normalized_count,
        "This invariant is valid for the current one-row-per-leaf canonical normalization")

    # Validate selected fact groups independently; unlike summing CNT,
    # distinct APP_ID membership is robust when rows are re-grouped.
    for fields in (("SOURCE",), ("SOURCE", "CHANGE_TYPE"), ("PATH", "DIFF_FLAG")):
        dims = list(fields)
        pivot = PivotRollup(connection, run_id="audit", data_revision="audit-1", signing_secret=b"audit-in-memory-key")
        result = pivot.cells(dimensions=dims, limit=sample_limit)
        mismatches = 0
        for cell in result["items"]:
            members = pivot.members(cell["group_locator"], limit=1)
            if cell["cnt"] != members["total"]:
                mismatches += 1
        run("pivot_membership_" + "_".join(fields).lower(), mismatches, 0,
            f"Verified {len(result['items'])} group cells; test uses exact member totals")
    return checks


def audit_checks_report(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate shared check result shape, not business PASS/FAIL verdicts."""
    if not isinstance(report, Mapping):
        raise AuditFailure("checks_report.json must contain an object")
    rows = report.get("checks")
    diagnostics = report.get("diagnostics")
    if not isinstance(rows, list) or not isinstance(diagnostics, list):
        raise AuditFailure("checks_report requires 'checks' and 'diagnostics' arrays")
    fields = {"LABEL", "SOURCE", "ARGUMENT", "CNT", "TOTAL", "METRIC", "APP_IDS", "RESULT", "CONFIDENCE"}
    invalid = 0
    for row in rows:
        if not isinstance(row, dict) or not fields.issubset(row):
            invalid += 1
            continue
        if (row["SOURCE"] not in ("BEFORE", "AFTER")
            or row["RESULT"] not in ("PASS", "FAIL")
            or row["CONFIDENCE"] not in ("HIGH", "LOW")
            or type(row["CNT"]) is not int or row["CNT"] < 0
            or type(row["TOTAL"]) is not int or row["TOTAL"] < 0
            or not isinstance(row["APP_IDS"], list)
            or not all(isinstance(a, str) for a in row["APP_IDS"])
            or not isinstance(row["METRIC"], (int, float))
            or isinstance(row["METRIC"], bool)):
            invalid += 1
    return [
        _check_record("check_execution_diagnostics", len(diagnostics), 0),
        _check_record("check_result_row_schema", invalid, 0,
                      details=f"Rows examined: {len(rows)}; APP_IDS may be a truncated sample"),
    ]


def generate_audit(connection: Any, *, checks_report: Mapping[str, Any] | None = None,
                   sample_limit: int = 30) -> dict[str, Any]:
    results = audit_database(connection, sample_limit=sample_limit)
    if checks_report is not None:
        results.extend(audit_checks_report(checks_report))
    failed = [r for r in results if not r["ok"]]
    return {"ok": not failed, "passed": len(results) - len(failed),
            "failed": len(failed), "checks": results}
