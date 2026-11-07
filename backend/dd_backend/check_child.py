"""Check child process (one per registration phase and one per check execution).

    python -I -m dd_backend.check_child register <check.py> <result.json>
    python -I -m dd_backend.check_child run <check.py> <mart.duckdb> <overrides.json> <result.json>

Uses D4 ports unchanged: decision_diff.check_runner.load_check / run_checks and
decision_diff.mart.DuckDBMart (read-only connection to this run's mart only).
The result is written to a file (stdout of user code is just a log).
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path


def _write(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


def register(check_path: Path, result: Path) -> int:
    from decision_diff.check_runner import CheckContractError, load_check
    try:
        definition = load_check(check_path)
    except CheckContractError as exc:
        _write(result, {"ok": False, "status": "CONTRACT_ERROR", "error_type": type(exc).__name__, "message": str(exc)})
        return 0
    except Exception as exc:
        _write(result, {"ok": False, "status": "IMPORT_ERROR", "error_type": type(exc).__name__, "message": str(exc),
                        "traceback": traceback.format_exc(limit=6)})
        return 0
    try:
        params = json.loads(json.dumps(definition["params"]))
    except (TypeError, ValueError):
        params = {"_unserializable": True}
    _write(result, {"ok": True, "id": definition["id"], "label": definition["label"], "params": params})
    return 0


def execute(check_path: Path, mart_path: Path, overrides_path: Path, result: Path) -> int:
    from decision_diff.check_runner import CheckContractError, run_checks
    from decision_diff.mart import DuckDBMart

    overrides = json.loads(overrides_path.read_text("utf-8"))
    with DuckDBMart(mart_path) as mart:
        outcome = run_checks(mart, [check_path], overrides)
        run_app_ids = {str(s["APP_ID"]) for s in mart.segments()}
    status = "SUCCEEDED"
    diagnostics = [dict(d, file=check_path.name) for d in outcome.diagnostics]
    rows = outcome.rows
    if diagnostics:
        status = "INVALID_OUTPUT" if any(d["error_type"] == CheckContractError.__name__ for d in diagnostics) else "ERROR"
        rows = []
    else:
        foreign = sorted({str(a) for r in rows for a in r["APP_IDS"]} - run_app_ids)
        if foreign:
            status = "INVALID_OUTPUT"
            diagnostics = [{"check": check_path.stem, "error_type": "ForeignAppIds",
                            "message": f"APP_IDS outside this run: {foreign[:5]}"}]
            rows = []
    try:
        json.dumps(rows)
    except (TypeError, ValueError) as exc:
        status, rows = "INVALID_OUTPUT", []
        diagnostics = [{"check": check_path.stem, "error_type": "NotJsonSerializable", "message": str(exc)}]
    _write(result, {"status": status, "rows": rows, "diagnostics": diagnostics, "timings": outcome.timings})
    return 0


def main() -> int:
    cmd = sys.argv[1]
    if cmd == "register":
        return register(Path(sys.argv[2]), Path(sys.argv[3]))
    if cmd == "run":
        return execute(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5]))
    return 64


if __name__ == "__main__":
    sys.exit(main())
