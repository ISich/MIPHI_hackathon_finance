"""Build an immutable per-run DuckDB database from an existing CLI output directory.

Keeping this as an independent import step lets the team test storage and
checks without changing the already validated normalizer/comparator.
"""
from __future__ import annotations

import csv
from pathlib import Path

import duckdb


TABLES: dict[str, tuple[str, set[str]]] = {
    "comparison": ("comparison.csv", {"DIFF_FLAG"}),
    "segments": ("segments.csv", {"DECISION_CHANGED"}),
    "pivot_facts": ("pivot_facts.csv", {"CNT"}),
    "normalized_union": ("normalized_union.csv", set()),
}


def _sql_literal(path: Path) -> str:
    """Escape filesystem path for SQL literal (not a table/column identifier)."""
    return "'" + str(path.resolve()).replace("'", "''") + "'"


def _validate_csv(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Required processing output is missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        header = next(csv.reader(stream, delimiter=";"), [])
    if not header or len(header) != len(set(header)):
        raise ValueError(f"CSV has missing/duplicate column names: {path}")


def build_database(output_dir: str | Path, db_path: str | Path, *, replace: bool = False) -> dict[str, int]:
    """Load generated CSV files into DuckDB and create lookup indexes.

    Intended for a completed run. A DB file is associated with *one* run.
    Close all readers before replacing a database on Windows.
    """
    source = Path(output_dir).resolve()
    target = Path(db_path).resolve()
    for filename, _ in TABLES.values():
        _validate_csv(source / filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not replace:
            raise FileExistsError(f"Database already exists: {target} (pass --replace)")
        target.unlink()
    con = duckdb.connect(str(target))
    counts: dict[str, int] = {}
    try:
        for table, (filename, number_columns) in TABLES.items():
            # SQL identifiers originate only from the fixed TABLES mapping.
            path = _sql_literal(source / filename)
            query = f"SELECT * FROM read_csv({path}, delim=';', header=true, all_varchar=true)"
            with (source / filename).open("r", encoding="utf-8-sig", newline="") as stream:
                columns = next(csv.reader(stream, delimiter=";"))
            selected = [
                f'CAST("{column}" AS INTEGER) AS "{column}"' if column in number_columns
                else f'COALESCE("{column}", \'\') AS "{column}"'
                for column in columns
            ]
            con.execute(f'CREATE TABLE "{table}" AS SELECT ' + ', '.join(selected) + f' FROM ({query})')
            counts[table] = int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        con.execute("CREATE INDEX idx_comparison_path ON comparison(PATH)")
        con.execute("CREATE INDEX idx_comparison_app ON comparison(APP_ID)")
        con.execute("CREATE INDEX idx_comparison_change ON comparison(CHANGE_TYPE)")
        con.execute("CREATE INDEX idx_segments_app ON segments(APP_ID)")
        con.execute("CREATE INDEX idx_pivot_path ON pivot_facts(PATH)")
        if counts["segments"] != con.execute("SELECT COUNT(DISTINCT APP_ID) FROM segments").fetchone()[0]:
            raise ValueError("Segments must have one row per APP_ID")
        if counts["comparison"] != con.execute(
            "SELECT COUNT(DISTINCT (APP_ID, PATH, ARRAY_KEY)) FROM comparison"
        ).fetchone()[0]:
            raise ValueError("Comparison mart contains duplicate attribute identities")
        return counts
    except Exception:
        con.close()
        if target.exists():
            target.unlink()
        raise
    finally:
        # On errors the connection is already closed; DuckDB close is idempotent.
        con.close()
