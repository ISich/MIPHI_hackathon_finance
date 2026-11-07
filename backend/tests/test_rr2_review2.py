"""Codex re-review #2 (cc8fc9c): regression tests, written before the fixes."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import make_client, wait_run
from helpers import config, copy_pair_dirs, demo_dataset, idem, start_run


def _alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return state != "Z"


# ---------------------------------------------------------------- #1 MAJOR
CRASH_SPAWNER = """
import os, subprocess, time
from decision_diff.core import normalize as core_normalize
from decision_diff.configs import REAL

def normalize(document, app_id, source, params):
    if source == 'BEFORE':
        p = subprocess.Popen(['sleep', '300'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(os.path.join(os.environ['HOME'], 'gc.pid'), 'w') as f:
            f.write(str(p.pid))
        time.sleep(60)
    return core_normalize(document, app_id, source, REAL)
"""


def test_worker_sigkill_descendants_are_cleaned_before_job_is_released(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("DD_EMBEDDED_WORKER", "0")
    with make_client() as api:
        ds = demo_dataset(api)
        s = api.post("/api/scripts", json={"kind": "normalize", "name": "c", "code": CRASH_SPAWNER}).json()
        run = start_run(api, config(api, ds["dataset_id"], checks=[], slots={"normalize": {"script_id": s["script_id"]}})["config_id"]).json()
        w1 = subprocess.Popen([sys.executable, "-m", "dd_backend", "worker"], env=dict(os.environ),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        pid_file = env["home"] / "runs" / run["run_id"] / "work" / "gc.pid"
        gc_pid = None
        try:
            deadline = time.time() + 30
            while not pid_file.exists() and time.time() < deadline:
                time.sleep(0.05)
            gc_pid = int(pid_file.read_text())
            os.kill(w1.pid, signal.SIGKILL)       # worker crash: no normal cleanup runs
            w1.wait()
            time.sleep(0.5)
            assert _alive(gc_pid)                 # PDEATHSIG does not reach grandchildren
            w2 = subprocess.Popen([sys.executable, "-m", "dd_backend", "worker"], env=dict(os.environ),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            try:
                failed = wait_run(api, run["run_id"])
                assert failed["error"]["code"] == "RUN_INTERRUPTED"
                deadline = time.time() + 5
                while _alive(gc_pid) and time.time() < deadline:
                    time.sleep(0.1)
                assert not _alive(gc_pid), "descendant of the crashed execution survived recovery"
            finally:
                os.killpg(w2.pid, signal.SIGTERM)
                w2.wait(timeout=30)
        finally:
            if gc_pid and _alive(gc_pid):
                os.kill(gc_pid, signal.SIGKILL)
            if w1.poll() is None:
                os.killpg(w1.pid, signal.SIGKILL)


# ---------------------------------------------------------------- #2 MAJOR
def _post_with_timeout(client, body, seconds=10):
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("r", client.post("/api/datasets", json=body)), daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), "registration request blocked"
    return box["r"]


def test_fifo_in_directory_dataset_is_rejected_without_blocking(client, env):
    root = copy_pair_dirs(env["core"], env["data"], n=1)
    os.mkfifo(root / "BEFORE" / "T0009.json")
    os.mkfifo(root / "AFTER" / "T0009.json")
    r = _post_with_timeout(client, {"name": "f", "root": "data", "mode": "dirs", "before": "set1/BEFORE", "after": "set1/AFTER"})
    assert r.status_code == 422 and r.json()["code"] == "DATASET_FILE_NOT_REGULAR"


def test_oversized_input_file_is_rejected_at_registration(env, monkeypatch):
    monkeypatch.setenv("DD_MAX_INPUT_FILE_BYTES", "1000")
    with make_client() as c:
        r = c.post("/api/datasets", json={"name": "big", "root": "examples", "mode": "files",
                                          "before": "I32554354_other.json", "after": "I32554354.json"})
        assert r.status_code == 422 and r.json()["code"] == "DATASET_FILE_TOO_LARGE"


def test_registration_hashes_with_bounded_reads(client, env, monkeypatch):
    from dd_backend import registry as reg_mod
    seen = []
    real_read = os.read

    def spy(fd, n):
        seen.append(n)
        return real_read(fd, n)
    monkeypatch.setattr(reg_mod.os, "read", spy)
    root = copy_pair_dirs(env["core"], env["data"], n=1)
    r = client.post("/api/datasets", json={"name": "b", "root": "data", "mode": "dirs", "before": "set1/BEFORE", "after": "set1/AFTER"})
    assert r.status_code == 201 and seen and max(seen) <= 1 << 20


# ---------------------------------------------------------------- #3 MAJOR
EXIT_AFTER_RESULT_RUN = """
import atexit, os

def run(mart, params=None):
    atexit.register(lambda: os._exit(7))
    return []

CHECK = {'id': 'exit_after_run', 'label': 'x', 'params': {}, 'entrypoint': run}
"""
EXIT_AFTER_RESULT_IMPORT = """
import atexit, os
atexit.register(lambda: os._exit(7))

def run(mart, params=None):
    return []

CHECK = {'id': 'exit_after_import', 'label': 'x', 'params': {}, 'entrypoint': run}
"""


def test_nonzero_child_exit_after_writing_result_is_an_execution_error(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    with make_client() as c:
        ds = demo_dataset(c)
        ids = [c.post("/api/scripts", json={"kind": "check", "name": n, "code": code}).json()["script_id"]
               for n, code in (("r", EXIT_AFTER_RESULT_RUN), ("i", EXIT_AFTER_RESULT_IMPORT))]
        done = wait_run(c, start_run(c, config(c, ds["dataset_id"], checks=[{"script_id": i} for i in ids])["config_id"]).json()["run_id"])
        rep = c.get(f"/api/runs/{done['run_id']}/checks").json()
        assert [e["execution_status"] for e in rep["executions"]] == ["ERROR", "ERROR"], rep["executions"]
        assert rep["completeness"] == "INCOMPLETE"
        assert any("exit" in d["message"].lower() for d in rep["diagnostics"])


# ---------------------------------------------------------------- #4 MINOR
def test_concurrent_identical_script_writes_do_not_fail(client, monkeypatch):
    from dd_backend import registry as reg_mod
    real_replace = reg_mod.os.replace
    calls = []

    def slow_replace(a, b):
        calls.append(a)
        time.sleep(0.3)
        return real_replace(a, b)
    monkeypatch.setattr(reg_mod.os, "replace", slow_replace)
    reg = client.app.state.registry
    owner = client.get("/api/session") and reg.db.one("SELECT owner_id FROM sessions LIMIT 1")["owner_id"]
    errors = []
    barrier = threading.Barrier(4)

    def go():
        barrier.wait()
        try:
            reg.create_script(owner, "check", "workspace", "same", b"x = 42\n", {})
        except Exception as exc:  # noqa: BLE001 - the regression is any exception here
            errors.append(repr(exc))
    threads = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert len(calls) >= 2, "race window not exercised"
    assert errors == []


# ---------------------------------------------------------------- #5 MINOR
def test_artifact_download_contract_is_binary_not_json(client):
    spec = client.app.openapi()
    content = spec["paths"]["/api/runs/{run_id}/artifacts/{artifact_id}"]["get"]["responses"]["200"]["content"]
    assert {"text/csv", "application/octet-stream"} <= set(content)   # not only JSON (summary.json is JSON)
    assert content["text/csv"]["schema"] == {"type": "string", "format": "binary"}
    ds = demo_dataset(client)
    done = wait_run(client, start_run(client, config(client, ds["dataset_id"], checks=[])["config_id"]).json()["run_id"])
    arts = {a["kind"]: a for a in client.get(f"/api/runs/{done['run_id']}/artifacts").json()["items"]}
    assert client.get(arts["comparison"]["download"]).headers["content-type"].startswith("text/csv")
    assert client.get(arts["mart"]["download"]).headers["content-type"] == "application/octet-stream"
