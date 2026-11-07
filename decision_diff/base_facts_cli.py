"""Local-only additive migration. D2 should integrate materialize_base_facts
into the one authorized AGGREGATING worker, not run this CLI in web requests.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .base_facts import materialize_base_facts


def main() -> None:
    parser = argparse.ArgumentParser(description="Create D4 base facts/membership")
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--replace', action='store_true')
    args = parser.parse_args()
    import duckdb

    if not args.db.is_file():
        parser.error(f'DuckDB file not found: {args.db}')
    conn = duckdb.connect(str(args.db))
    try:
        counts = materialize_base_facts(conn, replace=args.replace)
        print(f'Base facts ready: {counts}')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
