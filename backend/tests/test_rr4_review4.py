"""Codex re-review #4 (60a61fd): regression tests, written before the fixes."""
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from conftest import make_client, wait_run
from helpers import config, demo_dataset, start_run


def _alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return state != "Z"


def _kill_if_alive(pid):
    if pid and _alive(pid):
        os.kill(pid, signal.SIGKILL)


ESCAPER = """
import os, subprocess, time
from decision_diff.core import normalize as core_normalize
from decision_diff.configs import REAL

def normalize(document, app_id, source, params):
    if source == 'BEFORE':
        p = subprocess.Popen(['/bin/sleep', '300'], env={}, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(os.path.join(os.environ['HOME'], 'esc.pid'), 'w') as f:
            f.write(str(p.pid))
        time.sleep(params.get('sleep', 60))
    return core_normalize(document, app_id, source, REAL)
"""


def _escaper_cfg(c, sleep=60):
    ds = demo_dataset(c)
    s = c.post("/api/scripts", json={"kind": "normalize", "name": "esc", "code": ESCAPER}).json()
    return ds, config(c, ds["dataset_id"], checks=[], slots={"normalize": {"script_id": s["script_id"], "params": {"sleep": sleep}}})


def _wait_file(p, timeout=30):
    deadline = time.time() + timeout
    while not p.exists() and time.time() < deadline:
        time.sleep(0.05)
    time.sleep(0.1)
    return int(p.read_text())


# ------------------------------------------------------------------ #1 MAJOR
CRASHING_WORKER = textwrap.dedent("""
    import os, signal, sys, time
    from pathlib import Path
    from dd_backend import worker as w
    from dd_backend.db import Database
    from dd_backend.settings import load_settings

    def crash_before_recording(self, job_seq, child):
        # worker dies after launching the supervisor but BEFORE persisting its identity
        pid_file = Path(sys.argv[1])
        deadline = time.time() + 30
        while not pid_file.exists() and time.time() < deadline:
            time.sleep(0.05)
        os.kill(child.pid, signal.SIGSTOP)   # supervisor cannot react yet
        os.kill(os.getpid(), signal.SIGKILL)

    w.Worker._record_supervisor = crash_before_recording
    s = load_settings()
    db = Database(s.db_path)
    db.init()
    w.Worker(s, db).run_forever()
""")


def test_crash_between_launch_and_identity_record_does_not_release(env, monkeypatch, tmp_path):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("DD_EMBEDDED_WORKER", "0")
    driver = tmp_path / "crashing_worker.py"
    driver.write_text(CRASHING_WORKER)
    with make_client() as api:
        db = api.app.state.db
        _, cfg = _escaper_cfg(api)
        run = start_run(api, cfg["config_id"]).json()
        queued = start_run(api, config(api, demo_dataset(api)["dataset_id"], checks=[])["config_id"]).json()
        pid_file = env["home"] / "runs" / run["run_id"] / "work" / "esc.pid"
        w1 = subprocess.Popen([sys.executable, str(driver), str(pid_file)], env=dict(os.environ),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        esc = sup = None
        try:
            w1.wait(timeout=60)
            esc = _wait_file(pid_file)
            mark = db.one("SELECT exec_mark FROM jobs WHERE ref_id=?", (run["run_id"],))["exec_mark"]
            assert db.one("SELECT exec_pgid FROM jobs WHERE ref_id=?", (run["run_id"],))["exec_pgid"] is None
            started = env["home"] / "executions" / f"{mark}.started"
            sup = int(started.read_text().split()[0]) if started.exists() else None
            w2 = subprocess.Popen([sys.executable, "-m", "dd_backend", "worker"], env=dict(os.environ),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            try:
                time.sleep(5)
                # supervisor identity known (from its own record) and alive but stopped -> not released
                assert api.get(f"/api/runs/{run['run_id']}").json()["status"] == "RUNNING"
                assert api.get(f"/api/runs/{queued['run_id']}").json()["status"] == "QUEUED"
                assert _alive(esc)
                assert sup is not None
                os.kill(sup, signal.SIGCONT)        # supervisor resumes, sees the worker gone, contains
                assert wait_run(api, run["run_id"])["error"]["code"] == "RUN_INTERRUPTED"
                assert not _alive(esc), "descendant survived; job was released"
                assert wait_run(api, queued["run_id"])["status"] == "COMPLETED"
            finally:
                os.killpg(w2.pid, signal.SIGTERM)
                w2.wait(timeout=30)
        finally:
            if sup:
                try:
                    os.kill(sup, signal.SIGCONT)
                except ProcessLookupError:
                    pass
            _kill_if_alive(esc)
            _kill_if_alive(sup)


# ------------------------------------------------------------------ #2 MAJOR
def test_exception_right_after_launch_still_stops_and_verifies_execution(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    from dd_backend import worker as worker_mod
    launched = []

    def boom(self, job_seq, child):
        launched.append(child.pid)
        raise RuntimeError("simulated failure after launch")
    monkeypatch.setattr(worker_mod.Worker, "_record_supervisor", boom)
    with make_client() as c:
        _, cfg = _escaper_cfg(c)
        done = wait_run(c, start_run(c, cfg["config_id"]).json()["run_id"])
        assert done["status"] == "FAILED" and done["error"]["code"] == "WORKER_ERROR"
        assert launched and not _alive(launched[0]), "supervisor left running after the exception"
        pid_file = env["home"] / "runs" / done["run_id"] / "work" / "esc.pid"
        if pid_file.exists():
            esc = int(pid_file.read_text())
            try:
                assert not _alive(esc)
            finally:
                _kill_if_alive(esc)


def test_exception_path_with_unverified_cleanup_fails_closed(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    from dd_backend import worker as worker_mod
    real_set_stage = worker_mod.Worker._set_stage
    escapes = []

    def failing_stage(self, run_id, stage, substep, message, code_ref=None, check_run_id=None):
        if stage == "NORMALIZING":
            pid_file = self.settings.runs_dir / run_id / "work" / "esc.pid"
            deadline = time.time() + 30
            while not pid_file.exists() and time.time() < deadline:
                time.sleep(0.05)
            escapes.append(int(pid_file.read_text()))
            raise RuntimeError("simulated failure while streaming events")
        return real_set_stage(self, run_id, stage, substep, message, code_ref, check_run_id)

    def hard_reap(self, child):      # escalation: supervisor killed before it could verify containment
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return child.wait()
    monkeypatch.setattr(worker_mod.Worker, "_set_stage", failing_stage)
    monkeypatch.setattr(worker_mod.Worker, "_reap_supervisor", hard_reap)
    with make_client() as c:
        _, cfg = _escaper_cfg(c)
        run = start_run(c, cfg["config_id"]).json()
        queued = start_run(c, config(c, demo_dataset(c)["dataset_id"], checks=[])["config_id"]).json()
        try:
            done = wait_run(c, run["run_id"])
            assert done["error"]["code"] == "EXECUTION_UNCONTAINED", done
            time.sleep(2)
            assert c.get(f"/api/runs/{queued['run_id']}").json()["status"] == "QUEUED"  # queue blocked
        finally:
            for pid in escapes:
                _kill_if_alive(pid)


# ------------------------------------------------------------------ #3 MAJOR
FIFO_AT_RESULT = """
import atexit, os, sys

def _swap():
    path = sys.argv[-1]
    os.unlink(path)
    os.mkfifo(path)
%s
def run(mart, params=None):
%s
    return []

CHECK = {'id': '%s', 'label': 'x', 'params': {}, 'entrypoint': run}
"""


@pytest.mark.parametrize("phase", ["register", "run"])
def test_fifo_protocol_file_does_not_block_the_worker(env, monkeypatch, phase):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    at_import = "atexit.register(_swap)\n" if phase == "register" else ""
    at_run = "    atexit.register(_swap)" if phase == "run" else "    pass"
    code = FIFO_AT_RESULT % (at_import, at_run, f"fifo_{phase}")
    with make_client() as c:
        ds = demo_dataset(c)
        sid = c.post("/api/scripts", json={"kind": "check", "name": "fifo", "code": code}).json()["script_id"]
        done = wait_run(c, start_run(c, config(c, ds["dataset_id"], checks=[{"script_id": sid}])["config_id"]).json()["run_id"],
                        timeout=60)
        rep = c.get(f"/api/runs/{done['run_id']}/checks").json()
        assert rep["executions"][0]["execution_status"] in ("ERROR", "INVALID_OUTPUT")
        assert rep["completeness"] == "INCOMPLETE"


def test_symlinked_protocol_file_is_rejected(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    code = """
import atexit, os, sys

def run(mart, params=None):
    def swap():
        path = sys.argv[-1]
        os.replace(path, path + '.real')
        os.symlink(path + '.real', path)
    atexit.register(swap)
    return []

CHECK = {'id': 'symlinked', 'label': 'x', 'params': {}, 'entrypoint': run}
"""
    with make_client() as c:
        ds = demo_dataset(c)
        sid = c.post("/api/scripts", json={"kind": "check", "name": "sym", "code": code}).json()["script_id"]
        done = wait_run(c, start_run(c, config(c, ds["dataset_id"], checks=[{"script_id": sid}])["config_id"]).json()["run_id"])
        rep = c.get(f"/api/runs/{done['run_id']}/checks").json()
        assert rep["executions"][0]["execution_status"] in ("ERROR", "INVALID_OUTPUT")


# ------------------------------------------------------------------ #4 decision: same-origin only
def test_cross_origin_is_not_supported_even_for_the_dev_ui_origin(client):
    ds = demo_dataset(client)
    body = {"name": "x", "dataset_id": ds["dataset_id"], "checks": []}
    for origin in ("http://127.0.0.1:5173", "http://localhost:5173"):
        r = client.post("/api/configurations", json=body, headers={"origin": origin})
        assert r.status_code == 403 and r.json()["code"] == "ORIGIN_NOT_ALLOWED", origin
        pre = client.options("/api/configurations", headers={"origin": origin, "access-control-request-method": "POST"})
        assert "access-control-allow-origin" not in pre.headers
        assert pre.status_code >= 400
    # same origin (as behind nginx /api or a Vite proxy that keeps Host) works; scheme may differ behind TLS
    assert client.post("/api/configurations", json=body, headers={"origin": "http://127.0.0.1"}).status_code == 201
    assert client.post("/api/configurations", json=body, headers={"origin": "https://127.0.0.1"}).status_code == 201
    assert client.get("/api/datasets", headers={"origin": "http://127.0.0.1:5173"}).headers.get(
        "access-control-allow-origin") is None


def test_allowed_origins_setting_is_gone(env, monkeypatch):
    monkeypatch.setenv("DD_ALLOWED_ORIGINS", "http://ui.example")
    from dd_backend.settings import SettingsError
    with pytest.raises(SettingsError, match="same-origin"):
        make_client()
