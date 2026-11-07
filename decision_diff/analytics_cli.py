"""CLI: generated CSV outputs -> DuckDB mart -> organizer checks report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from .check_runner import discover_checks, run_checks
from .mart import DuckDBMart
from .storage import build_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Create DuckDB mart and run organizer checks")
    parser.add_argument("--data", type=Path, required=True, help="Directory with generated CSV outputs")
    parser.add_argument("--checks", type=Path, required=True, help="Directory with check_*.py")
    parser.add_argument("--db", type=Path, default=None, help="DuckDB database file (default: DATA/mart.duckdb)")
    parser.add_argument("--replace", action="store_true", help="Replace existing DB; close existing readers first")
    args = parser.parse_args()
    db = args.db or args.data / "mart.duckdb"
    t0 = perf_counter()
    table_counts = build_database(args.data, db, replace=args.replace)
    check_files = discover_checks(args.checks)
    if not check_files:
        parser.error(f"No check_*.py found in {args.checks}")
    with DuckDBMart(db) as mart:
        outcome = run_checks(mart, check_files)
        total = mart.total_apps()
        changed = len(mart.app_ids(diff_flag=1))
        decision_changed = sum(int(row["DECISION_CHANGED"]) for row in mart.segments())
    report = {
        "summary": {"total_apps": total, "changed_apps": changed, "decision_changed_apps": decision_changed},
        "tables": table_counts,
        "checks": outcome.rows,
        "diagnostics": outcome.diagnostics,
        "timings_seconds": outcome.timings,
    }
    result_path = args.data / "checks_report.json"
    result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"DuckDB: {db}")
    print(f"Table rows: {table_counts}")
    print(f"Applications: {total}; changed: {changed}; decision changed: {decision_changed}")
    print(f"Checks loaded: {len(check_files)}; rows: {len(outcome.rows)}; errors: {len(outcome.diagnostics)}")
    for issue in outcome.diagnostics:
        print(f"CHECK ERROR [{issue['check']}]: {issue['error_type']}: {issue['message']}")
    print(f"Elapsed: {perf_counter() - t0:.2f}s")
    print(f"Report: {result_path.resolve()}")
    if outcome.diagnostics:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
