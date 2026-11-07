"""Codex re-review #3 (f617212): regression tests, written before the fixes."""
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import make_client, wait_check_run, wait_run
from helpers import config, demo_dataset, idem, start_run


def _alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return state != "Z"


def _kill_if_alive(pid):
    if pid and _alive(pid):
        os.kill(pid, signal.SIGKILL)


def _worker(env_vars):
    return subprocess.Popen([sys.executable, "-m", "dd_backend", "worker"], env=env_vars,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


# ------------------------------------------------------------------ #1 MAJOR
def test_recovery_preserves_resources_that_already_reached_a_terminal_state(client):
    db = client.app.state.db
    ds = demo_dataset(client)
    done = wait_run(client, start_run(client, config(client, ds["dataset_id"])["config_id"]).json()["run_id"])
    check = next(s for s in client.get("/api/scripts?kind=check").json() if s["source"] == "builtin")
    cr = client.post(f"/api/runs/{done['run_id']}/check-runs", json={"checks": [{"script_id": check["script_id"]}]},
                     headers=idem()).json()
    cr_done = wait_check_run(client, cr["check_run_id"])
    assert done["status"] == cr_done["status"] == "COMPLETED"
    time.sleep(0.5)
    assert all(j["status"] == "DONE" for j in db.all("SELECT status FROM jobs"))
    # crash exactly between "resource COMPLETED" and "job DONE", owned by a worker that no longer exists
    with db.tx() as con:
        con.execute("UPDATE jobs SET status='RUNNING'")
        con.execute("UPDATE runs SET worker_id='wrk_gone' WHERE run_id=?", (done["run_id"],))
        con.execute("UPDATE check_runs SET worker_id='wrk_gone' WHERE check_run_id=?", (cr["check_run_id"],))
    from dd_backend.worker import Worker
    Worker(client.app.state.settings, db).recover()
    assert client.get(f"/api/runs/{done['run_id']}").json()["status"] == "COMPLETED"
    after = client.get(f"/api/check-runs/{cr['check_run_id']}").json()
    assert after["status"] == "COMPLETED" and after["error"] is None
    assert client.get(f"/api/reports/{cr['report_id']}").json()["status"] == "PUBLISHED"
    assert all(j["status"] == "DONE" for j in db.all("SELECT status FROM jobs"))


def test_terminal_state_and_job_done_commit_together(client, monkeypatch):
    """No commit boundary between them: once a run is terminal its job is already DONE."""
    db = client.app.state.db
    seen = []
    real_tx = db.tx

    class Wrap:
        def __init__(self):
            self.cm = real_tx()

        def __enter__(self):
            return self.cm.__enter__()

        def __exit__(self, *exc):
            out = self.cm.__exit__(*exc)
            rows = db.all("SELECT r.status AS rs, j.status AS js FROM runs r JOIN jobs j ON j.ref_id = r.run_id")
            seen.extend((r["rs"], r["js"]) for r in rows)
            return out
    monkeypatch.setattr(db, "tx", Wrap)
    ds = demo_dataset(client)
    wait_run(client, start_run(client, config(client, ds["dataset_id"], checks=[])["config_id"]).json()["run_id"])
    time.sleep(0.5)
    assert ("COMPLETED", "RUNNING") not in seen and ("FAILED", "RUNNING") not in seen


# ------------------------------------------------------------------ #2 MAJOR
ESCAPER = """
import os, subprocess, time
from decision_diff.core import normalize as core_normalize
from decision_diff.configs import REAL

def normalize(document, app_id, source, params):
    if source == 'BEFORE':
        # explicit empty environment (no execution mark) AND its own session: escapes group and mark
        p = subprocess.Popen(['/bin/sleep', '300'], env={}, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(os.path.join(os.environ['HOME'], 'esc.pid'), 'w') as f:
            f.write(str(p.pid))
        time.sleep(60)
    return core_normalize(document, app_id, source, REAL)
"""


@pytest.fixture
def ext(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("DD_EMBEDDED_WORKER", "0")
    with make_client() as api:
        yield api


def _escaper_run(api, env):
    ds = demo_dataset(api)
    s = api.post("/api/scripts", json={"kind": "normalize", "name": "esc", "code": ESCAPER}).json()
    run = start_run(api, config(api, ds["dataset_id"], checks=[], slots={"normalize": {"script_id": s["script_id"]}})["config_id"]).json()
    queued = start_run(api, config(api, ds["dataset_id"], checks=[])["config_id"]).json()
    return run, queued, env["home"] / "runs" / run["run_id"] / "work" / "esc.pid"


def _wait_file(p, timeout=30):
    deadline = time.time() + timeout
    while not p.exists() and time.time() < deadline:
        time.sleep(0.05)
    time.sleep(0.1)
    return int(p.read_text())


def test_escaped_descendant_without_mark_is_killed_before_release(ext, env):
    api = ext
    run, queued, pid_file = _escaper_run(api, env)
    w1 = _worker(dict(os.environ))
    esc = None
    try:
        esc = _wait_file(pid_file)
        os.kill(w1.pid, signal.SIGKILL)
        w1.wait()
        w2 = _worker(dict(os.environ))
        try:
            assert wait_run(api, run["run_id"])["error"]["code"] == "RUN_INTERRUPTED"
            deadline = time.time() + 5
            while _alive(esc) and time.time() < deadline:
                time.sleep(0.1)
            assert not _alive(esc), "escaped descendant survived; job was released"
            assert wait_run(api, queued["run_id"])["status"] == "COMPLETED"
        finally:
            os.killpg(w2.pid, signal.SIGTERM)
            w2.wait(timeout=30)
    finally:
        _kill_if_alive(esc)
        if w1.poll() is None:
            os.killpg(w1.pid, signal.SIGKILL)


def test_unverifiable_cleanup_fails_closed(ext, env):
    """Worker AND its containment process killed hard: cleanup cannot be verified -> job not released."""
    api = ext
    db = api.app.state.db
    run, queued, pid_file = _escaper_run(api, env)
    w1 = _worker(dict(os.environ))
    esc = None
    try:
        esc = _wait_file(pid_file)
        sup = db.one("SELECT exec_pgid FROM jobs WHERE ref_id=?", (run["run_id"],))["exec_pgid"]
        os.kill(w1.pid, signal.SIGSTOP)
        os.kill(sup, signal.SIGKILL)          # containment process lost without cleanup
        os.kill(w1.pid, signal.SIGKILL)
        w1.wait()
        w2 = _worker(dict(os.environ))
        try:
            time.sleep(6)
            assert api.get(f"/api/runs/{run['run_id']}").json()["status"] == "RUNNING"   # not released
            assert api.get(f"/api/runs/{queued['run_id']}").json()["status"] == "QUEUED"  # nothing overlaps
            ready = {c["name"]: c for c in api.get("/ready").json()["checks"]}
            assert ready["executions"]["ok"] is False
            # operator verifies and releases explicitly
            _kill_if_alive(esc)
            r = subprocess.run([sys.executable, "-m", "dd_backend", "release-job", "--ref", run["run_id"],
                                "--confirm-no-processes"], env=dict(os.environ), capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
            assert wait_run(api, run["run_id"])["error"]["code"] == "EXECUTION_UNCONTAINED"
            assert wait_run(api, queued["run_id"])["status"] == "COMPLETED"
        finally:
            os.killpg(w2.pid, signal.SIGTERM)
            w2.wait(timeout=30)
    finally:
        _kill_if_alive(esc)
        if w1.poll() is None:
            os.killpg(w1.pid, signal.SIGKILL)


def test_timeout_kills_escaped_descendants(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("DD_RUN_TIMEOUT_SECONDS", "8")
    with make_client() as c:
        run, _, pid_file = _escaper_run(c, env)
        esc = _wait_file(pid_file)
        try:
            assert wait_run(c, run["run_id"], timeout=60)["error"]["code"] == "TIMEOUT"
            deadline = time.time() + 5
            while _alive(esc) and time.time() < deadline:
                time.sleep(0.1)
            assert not _alive(esc)
        finally:
            _kill_if_alive(esc)


# ------------------------------------------------------------------ #3 MAJOR
BIG = """
def run(mart, params=None):
    row = {'LABEL': 'big', 'SOURCE': 'AFTER', 'ARGUMENT': 'x' * 1000, 'CNT': 0, 'TOTAL': 1, 'METRIC': 0.0,
           'APP_IDS': [], 'RESULT': 'PASS', 'CONFIDENCE': 'LOW'}
    return [dict(row) for _ in range(params['n'])]

CHECK = {'id': '%s', 'label': 'big', 'params': {'n': 1}, 'entrypoint': run}
"""


def test_oversized_check_result_is_rejected_without_loading_it(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("DD_MAX_CHECK_RESULT_BYTES", "100000")
    monkeypatch.setenv("DD_MAX_REPORT_BYTES", "150000")
    from dd_backend import worker as worker_mod
    loads_sizes = []
    real_loads = worker_mod.json.loads

    def spy(data, *a, **k):
        loads_sizes.append(len(data))
        return real_loads(data, *a, **k)
    monkeypatch.setattr(worker_mod.json, "loads", spy)
    with make_client() as c:
        ds = demo_dataset(c)
        ids = [c.post("/api/scripts", json={"kind": "check", "name": n, "code": BIG % n}).json()["script_id"]
               for n in ("huge", "half1", "half2")]
        checks = [{"script_id": ids[0], "params": {"n": 5000}},    # ~5 MB > per-check limit
                  {"script_id": ids[1], "params": {"n": 80}},      # ~90 KB, fits
                  {"script_id": ids[2], "params": {"n": 80}}]      # fits alone, exceeds the report budget
        done = wait_run(c, start_run(c, config(c, ds["dataset_id"], checks=checks)["config_id"]).json()["run_id"])
        rep = c.get(f"/api/runs/{done['run_id']}/checks").json()
        assert [e["execution_status"] for e in rep["executions"]] == ["INVALID_OUTPUT", "SUCCEEDED", "INVALID_OUTPUT"]
        assert rep["completeness"] == "INCOMPLETE"
        assert max(loads_sizes) < 200000, "worker decoded an oversized protocol file"


# ------------------------------------------------------------------ #4 MINOR
def test_concurrent_signing_key_initialization_is_consistent(tmp_path, monkeypatch):
    from dd_backend import app as app_mod
    real = app_mod.secrets.token_bytes

    def slow(n):
        time.sleep(0.3)
        return real(n)
    monkeypatch.setattr(app_mod.secrets, "token_bytes", slow)
    path = tmp_path / "pivot-locator.key"
    keys = [None] * 6
    barrier = threading.Barrier(6)

    def go(i):
        barrier.wait()
        keys[i] = app_mod._signing_key(path)
    ts = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    [t.start() for t in ts]
    [t.join(10) for t in ts]
    assert all(k is not None and len(k) == 32 for k in keys), [len(k or b"") for k in keys]
    assert len(set(keys)) == 1 and path.read_bytes() == keys[0]


def test_truncated_signing_key_is_refused(tmp_path):
    from dd_backend import app as app_mod
    path = tmp_path / "pivot-locator.key"
    path.write_bytes(b"")
    with pytest.raises(RuntimeError):
        app_mod._signing_key(path)
