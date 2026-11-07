"""Read-only report queries over an already completed per-run DuckDB mart.

No FastAPI, Vue or worker dependency. D2 can instantiate this class per request
and expose its JSON-compatible return values through HTTP.

CNT semantics: a full pivot-fact identity counts DISTINCT applications, whereas
partial groupings may contain multiple attributes of the same application.
`member_count` always means distinct APP_IDs (not summed attribute facts).
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any


class ReportQueryError(ValueError):
    """The requested report group, paging or filtering is unsupported."""


GROUP_DIMENSIONS = frozenset({
    "PREFIX", "CLASS", "SUFFIX", "ARRAY_KEY", "KEY", "PATH",
    "VALUE_ADJUSTED", "DIFF_FLAG", "SOURCE",
})
SOURCE_VALUES = frozenset({"BEFORE", "AFTER"})


def _page(limit: int, offset: int) -> None:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ReportQueryError("limit must be an integer from 1 to 500")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ReportQueryError("offset must be a nonnegative integer")


def build_group_where(group: Mapping[str, Any]) -> tuple[str, list[Any]]:
    """Build a safe SQL predicate using fixed columns and parameterized values.

    A SOURCE must be explicitly specified. For ATTRIBUTE_NEW / ATTRIBUTE_LOST,
    the absent slice must never contribute a reporting row. No user-provided
    column name is interpolated unless it belongs to GROUP_DIMENSIONS.
    """
    if not isinstance(group, Mapping):
        raise ReportQueryError("group must be a mapping")
    if not set(group).issubset(GROUP_DIMENSIONS):
        raise ReportQueryError(f"Unsupported pivot dimensions: {set(group) - GROUP_DIMENSIONS}")
    source = group.get("SOURCE")
    if source not in SOURCE_VALUES:
        raise ReportQueryError("SOURCE must be BEFORE or AFTER")
    conditions = ["CHANGE_TYPE <> ?"]
    params: list[Any] = ["ATTRIBUTE_NEW" if source == "BEFORE" else "ATTRIBUTE_LOST"]
    for key, value in group.items():
        if key == "SOURCE":
            continue
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ReportQueryError(f"Unsupported value for {key}")
        if key == "VALUE_ADJUSTED":
            column = "ADJUSTED_BEFORE" if source == "BEFORE" else "ADJUSTED_AFTER"
        elif key == "DIFF_FLAG":
            if str(value) not in {"0", "1"}:
                raise ReportQueryError("DIFF_FLAG must be 0 or 1")
            column = "DIFF_FLAG"
            value = int(value)
        else:
            column = key
        conditions.append(f'"{column}" = ?')
        params.append(value)
    return " AND ".join(conditions), params


class ReportService:
    """A new read-only connection per instance; do not share between threads.

    Provide a stable per-run `db_path` obtained from D2's authorized run
    repository; do not accept an arbitrary path directly from a browser.
    """

    def __init__(self, db_path: str | Path) -> None:
        import duckdb

        self.db_path = Path(db_path).resolve()
        if not self.db_path.is_file():
            raise FileNotFoundError(self.db_path)
        self._db = duckdb.connect(str(self.db_path), read_only=True)

    def __enter__(self) -> "ReportService":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def _rows(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        cur = self._db.execute(sql, params or [])
        columns = [column[0] for column in cur.description]
        return [dict(zip(columns, record)) for record in cur.fetchall()]

    def summary(self) -> dict[str, Any]:
        """Calculate summary from persisted data, independent of JSON report."""
        stats = self._db.execute("""
            SELECT COUNT(*) AS total_apps,
                   SUM(CAST(DECISION_CHANGED AS BIGINT)) AS decision_changed_apps,
                   SUM(CASE WHEN DECISION_BEFORE='APPROVE' THEN 1 ELSE 0 END) AS approved_before,
                   SUM(CASE WHEN DECISION_AFTER='APPROVE' THEN 1 ELSE 0 END) AS approved_after
            FROM segments
        """).fetchone()
        total, decisions, before, after = (int(x or 0) for x in stats)
        changed = int(self._db.execute(
            "SELECT COUNT(DISTINCT APP_ID) FROM comparison WHERE DIFF_FLAG = 1"
        ).fetchone()[0])
        return {
            "total_apps": total,
            "changed_apps": changed,
            "decision_changed_apps": decisions,
            "approval_rate_before": round(before / total, 6) if total else 0.0,
            "approval_rate_after": round(after / total, 6) if total else 0.0,
        }

    def top_changed_paths(self, *, limit: int = 20) -> list[dict[str, Any]]:
        _page(limit, 0)
        return self._rows("""
            SELECT PATH, COUNT(DISTINCT APP_ID) AS APP_COUNT,
                   COUNT(*) AS ATTRIBUTE_CHANGES
            FROM comparison WHERE DIFF_FLAG = 1
            GROUP BY PATH ORDER BY APP_COUNT DESC, PATH LIMIT ?
        """, [limit])

    def group_members(
        self, group: Mapping[str, Any], *, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Get a true distinct-app count and a page of APP_IDs for pivot group.

        `group` can contain partial dimensions (SOURCE required). The count is
        DISTINCT APP_ID even for partial/rolled-up groups, avoiding false totals
        from summing multiple attribute rows belonging to the same application.
        """
        _page(limit, offset)
        where, params = build_group_where(group)
        count = int(self._db.execute(
            f"SELECT COUNT(DISTINCT APP_ID) FROM comparison WHERE {where}", params
        ).fetchone()[0])
        app_ids = [str(row[0]) for row in self._db.execute(
            f"SELECT DISTINCT APP_ID FROM comparison WHERE {where} ORDER BY APP_ID LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()]
        return {
            "group": dict(group),
            "total": count,
            "items": app_ids,
            "limit": limit,
            "offset": offset,
        }

    def application(self, app_id: str, *, changed_only: bool = False) -> dict[str, Any]:
        if not isinstance(app_id, str) or not app_id:
            raise ReportQueryError("app_id must be a nonempty string")
        segments = self._rows("SELECT * FROM segments WHERE APP_ID = ?", [app_id])
        if not segments:
            raise KeyError(f"Unknown application: {app_id}")
        where = "APP_ID = ? AND DIFF_FLAG = 1" if changed_only else "APP_ID = ?"
        rows = self._rows(
            f"SELECT * FROM comparison WHERE {where} ORDER BY PATH, ARRAY_KEY", [app_id]
        )
        return {"APP_ID": app_id, "segment": segments[0], "attributes": rows}

    def pivot_facts(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        _page(limit, offset)
        total = int(self._db.execute("SELECT COUNT(*) FROM pivot_facts").fetchone()[0])
        rows = self._rows(
            "SELECT * FROM pivot_facts ORDER BY PATH, ARRAY_KEY, SOURCE, VALUE_ADJUSTED LIMIT ? OFFSET ?",
            [limit, offset],
        )
        return {"total": total, "items": rows, "limit": limit, "offset": offset,
                "count_semantics": "attribute_memberships_per_pivot_group"}

    def validate_memberships(self, *, sample_limit: int = 25) -> dict[str, Any]:
        """Check sample full-dimensional pivot groups against comparison mart.

        Runs after ingestion, not on every web request. Full group identity
        must have a unique row per APP_ID, so DISTINCT membership == CNT.
        """
        _page(sample_limit, 0)
        groups = self._rows("""
            SELECT PREFIX, CLASS, SUFFIX, ARRAY_KEY, KEY, PATH,
                   VALUE_ADJUSTED, DIFF_FLAG, SOURCE, CNT
            FROM pivot_facts ORDER BY PATH, ARRAY_KEY, SOURCE, VALUE_ADJUSTED
            LIMIT ?
        """, [sample_limit])
        mismatches: list[dict[str, Any]] = []
        for fact in groups:
            dims = {key: fact[key] for key in GROUP_DIMENSIONS}
            match_count = self.group_members(dims, limit=1)["total"]
            if match_count != int(fact["CNT"]):
                mismatches.append({"group": dims, "fact_count": int(fact["CNT"]),
                                   "member_count": match_count})
        return {"checked": len(groups), "mismatches": mismatches, "ok": not mismatches}
