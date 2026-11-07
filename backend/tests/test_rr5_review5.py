"""Codex re-review #5 (e7d0b80): regression tests, written before the fixes."""
import os
import signal
import threading
import time
from pathlib import Path

import pytest

from conftest import make_client, wait_run
from helpers import config, demo_dataset, start_run


def _my_detached_descendants() -> list[int]:
    """Processes forked from this pytest process that went into their own session (our test only)."""
    me, my_sid = os.getpid(), os.getsid(0)
    out = []
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            fields = Path(entry.path, "stat").read_text().rsplit(")", 1)[1].split()
        except OSError:
            continue
        if int(fields[1]) == me and int(fields[3]) != my_sid:
            out.append(int(entry.name))
    return out


# ------------------------------------------------------------------ #1 MAJOR
def test_no_python_runs_between_fork_and_exec_and_limits_still_apply(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("DD_MAX_MEMORY_MB", "3000")
    monkeypatch.setenv("DD_MAX_OUTPUT_BYTES", str(512 * 1024 * 1024))
    from dd_backend import worker as worker_mod
    held = threading.Lock()
    held.acquire()  # held by this thread for the whole test: a forked copy can never take it

    def deadlocking_limits(self):
        return lambda: held.acquire()   # what an inherited lock does to a preexec_fn
    monkeypatch.setattr(worker_mod.Worker, "_limits", deadlocking_limits, raising=False)
    probe = """
import os, resource
from decision_diff.core import normalize as core_normalize
from decision_diff.configs import REAL

def normalize(document, app_id, source, params):
    assert resource.getrlimit(resource.RLIMIT_AS)[0] == 3000 * 1024 * 1024, resource.getrlimit(resource.RLIMIT_AS)
    assert resource.getrlimit(resource.RLIMIT_FSIZE)[0] == 512 * 1024 * 1024
    assert resource.getrlimit(resource.RLIMIT_CORE)[0] == 0
    assert (os.umask(0o077) == 0o077)
    return core_normalize(document, app_id, source, REAL)
"""
    try:
        with make_client() as c:
            ds = demo_dataset(c)
            s = c.post("/api/scripts", json={"kind": "normalize", "name": "probe", "code": probe}).json()
            cfg = config(c, ds["dataset_id"], checks=[], slots={"normalize": {"script_id": s["script_id"]}})
            done = wait_run(c, start_run(c, cfg["config_id"]).json()["run_id"], timeout=40)
            assert done["status"] == "COMPLETED", done
    finally:
        for pid in _my_detached_descendants():
            os.kill(pid, signal.SIGKILL)
        held.release()


# ------------------------------------------------------------------ #2 MAJOR
TAMPER = """
import atexit, json, sys
PAYLOAD = %s

def _tamper():
    with open(sys.argv[-1], 'w') as f:
        f.write(json.dumps(PAYLOAD))
%s
def run(mart, params=None):
%s
    return []

CHECK = {'id': '%s', 'label': 'x', 'params': {}, 'entrypoint': run}
"""
CASES = {
    "reg_empty": ({}, "register"),
    "reg_bad_types": ({"ok": True, "id": 5, "label": None, "params": []}, "register"),
    "run_empty": ({}, "run"),
    "run_bad_status": ({"status": "WEIRD", "rows": [], "diagnostics": []}, "run"),
    "run_bad_rows": ({"status": "SUCCEEDED", "rows": [{"x": 1}], "diagnostics": []}, "run"),
    "run_rows_not_list": ({"status": "SUCCEEDED", "rows": "nope", "diagnostics": {}}, "run"),
}


def test_malformed_protocol_objects_are_isolated_per_check(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    healthy = """
def run(mart, params=None):
    return []

CHECK = {'id': 'healthy', 'label': 'ok', 'params': {}, 'entrypoint': run}
"""
    with make_client() as c:
        ds = demo_dataset(c)
        ids = []
        for name, (payload, phase) in CASES.items():
            code = TAMPER % (repr(payload), "atexit.register(_tamper)\n" if phase == "register" else "",
                             "    atexit.register(_tamper)" if phase == "run" else "    pass", name)
            ids.append(c.post("/api/scripts", json={"kind": "check", "name": name, "code": code}).json()["script_id"])
        ids.append(c.post("/api/scripts", json={"kind": "check", "name": "healthy", "code": healthy}).json()["script_id"])
        done = wait_run(c, start_run(c, config(c, ds["dataset_id"], checks=[{"script_id": i} for i in ids])["config_id"]).json()["run_id"])
        assert done["status"] == "COMPLETED", done          # not WORKER_ERROR for the whole job
        rep = c.get(f"/api/runs/{done['run_id']}/checks")
        assert rep.status_code == 200, rep.text              # report validates against the response model
        statuses = [e["execution_status"] for e in rep.json()["executions"]]
        assert statuses[:-1] == ["INVALID_OUTPUT"] * len(CASES), statuses
        assert statuses[-1] == "SUCCEEDED"
        assert rep.json()["checks"] == []


# ------------------------------------------------------------------ #3 MINOR
def test_concurrent_first_initialization_of_a_fresh_database(tmp_path, monkeypatch):
    from dd_backend.db import Database
    import sqlite3
    real_connect = Database.connect

    class SlowInspect:
        """Widen the window between 'column missing?' and 'ALTER TABLE'."""
        def __init__(self, con):
            self._con = con

        def execute(self, sql, *a):
            cur = self._con.execute(sql, *a)
            if sql.startswith("PRAGMA table_info"):
                rows = cur.fetchall()
                time.sleep(0.3)
                return rows
            return cur

        def __getattr__(self, name):
            return getattr(self._con, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self._con.__exit__(*exc)
    monkeypatch.setattr(Database, "connect", lambda self: SlowInspect(real_connect(self)))
    # an old-schema database (before the migrations) so every starter sees the columns missing
    path = tmp_path / "old.sqlite3"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE workers (worker_id TEXT PRIMARY KEY, pid INTEGER NOT NULL, hostname TEXT NOT NULL,
                              started_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL);
        CREATE TABLE jobs (job_seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, ref_id TEXT NOT NULL UNIQUE,
                           status TEXT NOT NULL, created_at TEXT NOT NULL);
    """)
    con.close()
    errors = []
    barrier = threading.Barrier(8)

    def go():
        barrier.wait()
        try:
            Database(path).init()
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
    ts = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    assert errors == []
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(jobs)")}
    assert {"exec_mark", "exec_pgid", "exec_start"} <= cols
