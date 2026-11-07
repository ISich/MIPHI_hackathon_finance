"""Readiness reflects real dependencies, not a constant true."""
from __future__ import annotations

import importlib.metadata
import json
from datetime import datetime, timezone
from typing import Any

from .db import Database
from .settings import Settings


def core_info() -> dict[str, Any]:
    import decision_diff  # noqa: F401  (import proves the package is usable)
    from decision_diff import check_runner, mart, storage  # noqa: F401  D4 ports

    dist = importlib.metadata.distribution("decision-diff-core")
    commit = None
    try:
        direct = json.loads(dist.read_text("direct_url.json") or "{}")
        commit = direct.get("vcs_info", {}).get("commit_id")
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {"version": dist.version, "commit": commit}


def _check(name: str, fn) -> dict[str, Any]:
    try:
        details = fn() or {}
        ok = details.pop("_ok", True)
        return {"name": name, "ok": bool(ok), "details": details}
    except Exception as exc:  # readiness must report, not crash
        return {"name": name, "ok": False, "details": {"error": type(exc).__name__, "message": str(exc)[:300]}}


def readiness(settings: Settings, db: Database) -> dict[str, Any]:
    def database():
        with db.tx() as con:
            con.execute("SELECT COUNT(*) FROM jobs").fetchone()
        return {}

    def core():
        info = core_info()
        info["expected_commit"] = settings.expected_core_commit
        info["_ok"] = info["commit"] == settings.expected_core_commit
        return info

    def duck():
        import duckdb
        con = duckdb.connect(":memory:")
        try:
            con.execute("SELECT 1").fetchone()
        finally:
            con.close()
        return {"version": duckdb.__version__}

    def checks():
        d = settings.checks_dir
        files = sorted(p.name for p in d.glob("check_*.py")) if d.is_dir() else []
        return {"_ok": bool(files), "count": len(files)}

    def roots():
        status = {name: path.is_dir() for name, path in settings.data_roots.items()}
        return {"_ok": bool(status) and all(status.values()), "roots": status}

    def worker():
        row = db.one("SELECT worker_id, heartbeat_at FROM workers ORDER BY heartbeat_at DESC LIMIT 1")
        if row is None:
            return {"_ok": False, "reason": "no worker heartbeat"}
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(row["heartbeat_at"].replace("Z", "+00:00"))).total_seconds()
        return {"_ok": age <= settings.worker_lease_seconds, "heartbeat_age_seconds": round(age, 1),
                "embedded": settings.embedded_worker}

    checks_list = [
        _check("database", database),
        _check("core_package", core),
        _check("duckdb", duck),
        _check("checks_dir", checks),
        _check("data_roots", roots),
        _check("worker", worker),
    ]
    return {
        "ready": all(c["ok"] for c in checks_list),
        "checks": checks_list,
        "execution_mode": settings.execution_mode,
        "warnings": (["trusted-local execution enabled: user Python runs with server user rights; loopback only"]
                     if settings.execution_mode == "trusted-local" else []),
    }
