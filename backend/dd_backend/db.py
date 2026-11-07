"""SQLite metadata store. One short-lived connection per unit of work.

Writes go through ``tx()`` which takes the write lock up front (BEGIN IMMEDIATE),
so the API process and the worker never interleave half-applied state.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS datasets (
    dataset_id TEXT PRIMARY KEY,
    owner_id TEXT,                       -- NULL: system dataset (shared read-only)
    name TEXT NOT NULL,
    root TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('files','dirs')),
    before_rel TEXT NOT NULL,
    after_rel TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dataset_revisions (
    revision_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
    fingerprint TEXT NOT NULL,
    pairs INTEGER NOT NULL,
    missing_before TEXT NOT NULL,
    missing_after TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scripts (
    script_id TEXT PRIMARY KEY,
    owner_id TEXT,                       -- NULL: built-in, shared read-only
    kind TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('builtin','workspace','file')),
    name TEXT NOT NULL,
    filename TEXT,
    builtin_ref TEXT,
    code_sha256 TEXT NOT NULL,
    code_rel TEXT,
    params_json TEXT NOT NULL,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_builtin_script ON scripts(builtin_ref) WHERE owner_id IS NULL;
CREATE TABLE IF NOT EXISTS configurations (
    config_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    name TEXT NOT NULL,
    dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
    slots_json TEXT NOT NULL,
    checks_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    config_id TEXT NOT NULL REFERENCES configurations(config_id),
    dataset_id TEXT NOT NULL,
    dataset_revision_id TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT,
    substep TEXT,
    processed INTEGER,
    total INTEGER,
    error_code TEXT,
    error_message TEXT,
    initial_check_run_id TEXT,
    initial_report_id TEXT,
    summary_json TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    worker_id TEXT,
    heartbeat_at TEXT
);
CREATE TABLE IF NOT EXISTS run_scripts (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    slot TEXT NOT NULL,
    script_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    name TEXT NOT NULL,
    script_revision INTEGER NOT NULL,
    code_sha256 TEXT NOT NULL,
    params_json TEXT NOT NULL,
    snapshot_rel TEXT NOT NULL,
    PRIMARY KEY (run_id, slot)
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    check_run_id TEXT,
    stage TEXT,
    substep TEXT,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    processed INTEGER,
    total INTEGER,
    code_ref TEXT,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    kind TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    rows INTEGER,
    bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS check_runs (
    check_run_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    owner_id TEXT NOT NULL,
    report_id TEXT NOT NULL,
    initial INTEGER NOT NULL,
    status TEXT NOT NULL,
    selected_json TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    worker_id TEXT,
    heartbeat_at TEXT
);
CREATE TABLE IF NOT EXISTS check_executions (
    execution_id TEXT PRIMARY KEY,
    check_run_id TEXT NOT NULL REFERENCES check_runs(check_run_id),
    slot TEXT NOT NULL,
    script_id TEXT NOT NULL,
    check_id TEXT,
    label TEXT,
    params_json TEXT NOT NULL,
    execution_status TEXT NOT NULL,
    diagnostics_json TEXT NOT NULL,
    rows_count INTEGER NOT NULL,
    duration_seconds REAL
);
CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    check_run_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    status TEXT NOT NULL,
    completeness TEXT,
    rel_path TEXT,
    sha256 TEXT,
    created_at TEXT NOT NULL,
    published_at TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    job_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('DATA_RUN','CHECK_RUN')),
    ref_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('QUEUED','RUNNING','DONE')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workers (
    worker_id TEXT PRIMARY KEY,
    pid INTEGER NOT NULL,
    hostname TEXT NOT NULL,
    started_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency (
    owner_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    result_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (owner_id, scope, key)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(10)}"


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = self.connect()
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)  # CREATE ... IF NOT EXISTS: idempotent under concurrency
            # Inspect-and-alter is one write transaction, so concurrent starters serialize here.
            con.execute("BEGIN IMMEDIATE")
            try:
                cols = {r[1] for r in con.execute("PRAGMA table_info(workers)")}
                if "proc_start" not in cols:  # migration: process identity for same-host liveness
                    con.execute("ALTER TABLE workers ADD COLUMN proc_start TEXT")
                jcols = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
                if "exec_mark" not in jcols:  # migration: identity of the running execution's processes
                    con.execute("ALTER TABLE jobs ADD COLUMN exec_mark TEXT")
                if "exec_pgid" not in jcols:
                    con.execute("ALTER TABLE jobs ADD COLUMN exec_pgid INTEGER")
                if "exec_start" not in jcols:
                    con.execute("ALTER TABLE jobs ADD COLUMN exec_start TEXT")
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=30000")
        return con

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        con = self.connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def one(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        con = self.connect()
        try:
            row = con.execute(sql, params).fetchone()
            return dict(row) if row is not None else None
        finally:
            con.close()

    def all(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        con = self.connect()
        try:
            return [dict(r) for r in con.execute(sql, params).fetchall()]
        finally:
            con.close()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def loads(value: str | None) -> Any:
    return None if value is None else json.loads(value)
