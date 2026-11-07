"""Stable D1/D4 entrypoints for a future platform runner.

This is a trusted in-process library, NOT a user-script sandbox.
D2 owns authentication, authorized run->artifact resolution, process isolation,
file ownership, runtime limits, immutable report identities, and API routing.
No DuckDB writes or global mutable connection are performed here.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .procedure_api import process_pair, config_to_dict
from .configs import REAL
from .check_runner import run_checks, CheckRunResult


def default_policy() -> dict[str, Any]:
    """Return a new JSON-safe dict; callers may edit it without mutating REAL."""
    return config_to_dict(REAL)


def process_application(
    *, before: Mapping[str, Any], after: Mapping[str, Any],
    app_id: str, normalization_params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """D1 default implementation, output validated by procedure_api.

    Raise ProcedureContractError on malformed normalized/comparison/segment data.
    A host runner should log the error and avoid publishing a completed Run.
    """
    if not isinstance(app_id, str) or not app_id:
        raise ValueError("app_id must be a nonempty string")
    return process_pair(
        before_doc=before,
        after_doc=after,
        app_id=app_id,
        params=normalization_params,
    )


def execute_trusted_checks(
    *, mart: Any, check_files: Sequence[str | Path],
    parameter_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """D4 CHECK protocol over a caller-scoped MartAPI instance.

    Check files are imported and executed! Only call in D2's constrained
    check-worker with explicitly approved files. A check execution failure is
    returned in diagnostics, never disguised as a business FAIL row.
    """
    result: CheckRunResult = run_checks(mart, check_files, parameter_overrides)
    return {
        "rows": result.rows,
        "diagnostics": result.diagnostics,
        "timings_seconds": result.timings,
        "complete": not bool(result.diagnostics),
    }


class AnalyticsReader:
    """Read-only, per-run D4 data API. Use one instance per request/worker.

    The caller must resolve an authorized, completed Run to db_path. Neither
    a browser-provided filesystem path nor a browser-provided signing secret
    is safe. These functions are not HTTP DTO definitions.
    """

    def __init__(
        self, *, db_path: str | Path, run_id: str, data_revision: str,
        signing_secret: bytes,
    ) -> None:
        if not run_id or not data_revision or not signing_secret:
            raise ValueError("run_id, data_revision and signing_secret are required")
        import duckdb
        from .report_service import ReportService
        from .pivot_rollup import PivotRollup

        self._db_path = Path(db_path).resolve()
        if not self._db_path.is_file():
            raise FileNotFoundError(self._db_path)
        self._connection = duckdb.connect(str(self._db_path), read_only=True)
        try:
            self._pivot = PivotRollup(
                self._connection, run_id=run_id,
                data_revision=data_revision, signing_secret=signing_secret,
            )
            self._report = ReportService(self._db_path)
        except BaseException:
            self._connection.close()
            raise
        self._closed = False

    def __enter__(self) -> "AnalyticsReader":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self._report.close()
            finally:
                self._connection.close()

    def summary(self) -> dict[str, Any]:
        return self._report.summary()

    def pivot(
        self, *, dimensions: Sequence[str], filters: Mapping[str, Any] | None = None,
        limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        return self._pivot.cells(
            dimensions=dimensions, filters=filters, limit=limit, offset=offset,
        )

    def group_members(self, *, group_locator: str, limit: int = 50,
                      offset: int = 0) -> dict[str, Any]:
        return self._pivot.members(group_locator, limit=limit, offset=offset)

    def application(self, *, app_id: str, changed_only: bool = False) -> dict[str, Any]:
        return self._report.application(app_id, changed_only=changed_only)

    def top_changed_paths(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return self._report.top_changed_paths(limit=limit)
