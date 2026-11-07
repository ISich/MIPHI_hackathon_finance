"""Command-line, read-only full-run audit. Does not reprocess input JSON."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate completed D1/D4 DuckDB artifacts")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--checks-report", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--sample-limit", type=int, default=30)
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error(f"Database does not exist: {args.db}")

    import duckdb
    from .audit import generate_audit

    checks_report = None
    if args.checks_report:
        checks_report = json.loads(args.checks_report.read_text(encoding="utf-8-sig"))
    conn = duckdb.connect(str(args.db), read_only=True)
    try:
        result = generate_audit(conn, checks_report=checks_report,
                                sample_limit=args.sample_limit)
    finally:
        conn.close()
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(serialized + "\n", encoding="utf-8")
        print(f"Audit report: {args.out.resolve()}")
    print(f"Audit status: {'PASS' if result['ok'] else 'FAIL'} "
          f"({result['passed']} passed, {result['failed']} failed)")
    for item in result["checks"]:
        print(f"{'PASS' if item['ok'] else 'FAIL'} {item['name']}: "
              f"actual={item['actual']} expected={item['expected']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
