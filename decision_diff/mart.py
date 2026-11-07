"""Read-only MartAPI adapter to the comparison tables in DuckDB.

The user-provided checks expect exactly five public methods. SQL filters are
whitelisted and all filter values are passed as SQL parameters.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb


class MartFilterError(ValueError):
    """An unsupported filter was requested by a check or a client."""


class DuckDBMart:
    """Open a *completed*, immutable per-run mart in read-only mode.

    Do not share this connection between simultaneous worker threads. Create
    separate DuckDBMart instances for concurrent readers and close each one.
    """

    _SCALAR_FILTERS = {
        "path": "PATH", "key": "KEY", "array_key": "ARRAY_KEY",
        "diff_flag": "DIFF_FLAG", "value_before": "VALUE_BEFORE",
        "value_after": "VALUE_AFTER", "change_type": "CHANGE_TYPE",
    }
    _LIST_FILTERS = {"path", "change_type", "app_ids"}

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).resolve()
        if not self.db_path.is_file():
            raise FileNotFoundError(f"Mart database does not exist: {self.db_path}")
        self._connection = duckdb.connect(str(self.db_path), read_only=True)

    def __enter__(self) -> "DuckDBMart":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        if isinstance(value, (str, bytes)):
            return [value]
        if isinstance(value, Sequence):
            return list(value)
        raise MartFilterError("Expected scalar text or list of values")

    @classmethod
    def _where(cls, filters: Mapping[str, Any]) -> tuple[str, list[Any]]:
        parts: list[str] = []
        params: list[Any] = []
        for name, value in filters.items():
            if name == "path_prefix":
                if not isinstance(value, str):
                    raise MartFilterError("path_prefix must be a string")
                parts.append("starts_with(PATH, ?)")
                params.append(value)
            elif name == "app_ids":
                values = cls._as_list(value)
                if not values:
                    parts.append("FALSE")
                else:
                    parts.append("APP_ID IN (" + ",".join("?" for _ in values) + ")")
                    params.extend(values)
            elif name in cls._SCALAR_FILTERS:
                column = cls._SCALAR_FILTERS[name]
                if name in cls._LIST_FILTERS and isinstance(value, (list, tuple, set, frozenset)):
                    values = list(value)
                    if not values:
                        parts.append("FALSE")
                    else:
                        parts.append(f"{column} IN (" + ",".join("?" for _ in values) + ")")
                        params.extend(values)
                else:
                    parts.append(f"{column} = ?")
                    if name == "diff_flag":
                        if value not in (0, 1, "0", "1"):
                            raise MartFilterError("diff_flag must be 0 or 1")
                        params.append(int(value))
                    else:
                        params.append(value)
            else:
                raise MartFilterError(f"Unsupported mart filter: {name}")
        return (" WHERE " + " AND ".join(parts) if parts else ""), params

    def _fetch_dicts(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        result = self._connection.execute(sql, params or [])
        columns = [column[0] for column in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def rows(self, **filters: Any) -> list[dict[str, Any]]:
        where, params = self._where(filters)
        return self._fetch_dicts("SELECT * FROM comparison" + where, params)

    def count(self, **filters: Any) -> int:
        where, params = self._where(filters)
        return int(self._connection.execute("SELECT COUNT(*) FROM comparison" + where, params).fetchone()[0])

    def app_ids(self, **filters: Any) -> list[str]:
        where, params = self._where(filters)
        result = self._connection.execute(
            "SELECT DISTINCT APP_ID FROM comparison" + where + " ORDER BY APP_ID", params
        )
        return [str(row[0]) for row in result.fetchall()]

    def segments(self) -> list[dict[str, Any]]:
        return self._fetch_dicts("SELECT * FROM segments ORDER BY APP_ID")

    def total_apps(self) -> int:
        return int(self._connection.execute("SELECT COUNT(*) FROM segments").fetchone()[0])

    # Additional functions used by the HTTP/report layer; not part of organizer's 5-method contract.
    def pivot(self, *, limit: int = 10000, offset: int = 0) -> list[dict[str, Any]]:
        if not (0 <= limit <= 100000 and offset >= 0):
            raise ValueError("Invalid pagination")
        return self._fetch_dicts("SELECT * FROM pivot_facts ORDER BY PATH, ARRAY_KEY, SOURCE, VALUE_ADJUSTED LIMIT ? OFFSET ?", [limit, offset])

    def pivot_app_ids(self, group: Mapping[str, Any], *, limit: int = 200) -> list[str]:
        """Drill-down: return APP_IDs that contributed to a pivot facts group.

        group is a mapping of one or more displayed pivot dimensions. A SOURCE
        must be provided so the bucket is matched against the correct slice.
        """
        if not (1 <= limit <= 10000):
            raise ValueError("Invalid application limit")
        if group.get("SOURCE") not in ("BEFORE", "AFTER"):
            raise MartFilterError("Pivot drill-down requires SOURCE BEFORE/AFTER")
        allowed = {"PREFIX", "CLASS", "SUFFIX", "ARRAY_KEY", "KEY", "PATH", "VALUE_ADJUSTED", "DIFF_FLAG", "SOURCE"}
        if not set(group).issubset(allowed):
            raise MartFilterError("Unknown pivot dimension")
        conditions: list[str] = []
        params: list[Any] = []
        for key, value in group.items():
            if key == "SOURCE":
                continue
            if key == "VALUE_ADJUSTED":
                side = "ADJUSTED_BEFORE" if group["SOURCE"] == "BEFORE" else "ADJUSTED_AFTER"
                conditions.append(f"{side} = ?")
            elif key == "DIFF_FLAG":
                conditions.append("DIFF_FLAG = ?")
                value = int(value)
            else:
                conditions.append(f"{key} = ?")
            params.append(value)
        # Do not include a value from the absent side of an attribute.
        excluded_change = "ATTRIBUTE_NEW" if group["SOURCE"] == "BEFORE" else "ATTRIBUTE_LOST"
        conditions.append("CHANGE_TYPE <> ?")
        params.append(excluded_change)
        query = "SELECT DISTINCT APP_ID FROM comparison WHERE " + " AND ".join(conditions)
        query += " ORDER BY APP_ID LIMIT ?"
        params.append(limit)
        return [str(row[0]) for row in self._connection.execute(query, params).fetchall()]

    def application(self, app_id: str) -> dict[str, Any]:
        segment = self._fetch_dicts("SELECT * FROM segments WHERE APP_ID = ?", [app_id])
        if not segment:
            raise KeyError(f"Unknown application {app_id}")
        comparison = self._fetch_dicts(
            "SELECT * FROM comparison WHERE APP_ID = ? ORDER BY PATH, ARRAY_KEY", [app_id]
        )
        return {"segment": segment[0], "comparison": comparison}
