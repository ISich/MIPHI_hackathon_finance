"""Slice D: execution safety, snapshots, limits, restart/interrupted jobs."""
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from conftest import BACKEND_DIR, make_client, wait_run
from helpers import config, demo_dataset, idem, start_run

SLOW_NORMALIZE = """
import time
from decision_diff.core import normalize as core_normalize
from decision_diff.configs import REAL

def normalize(document, app_id, source, params):
    time.sleep(params.get('sleep', 0))
    return core_normalize(document, app_id, source, REAL)
"""

V1 = """
from decision_diff.core import normalize as core_normalize
from decision_diff.configs import REAL
VERSION = 1

def normalize(document, app_id, source, params):
    return core_normalize(document, app_id, source, REAL)
"""

V2 = """
from decision_diff.core import normalize as core_normalize
from decision_diff.configs import REAL
VERSION = 2

def normalize(document, app_id, source, params):
    rows = core_normalize(document, app_id, source, REAL)
    return [r for r in rows if not r['PATH'].startswith('decisionResult.')]
"""


@pytest.fixture
def trusted(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    with make_client() as c:
        yield c


def _script(client, code, kind="normalize", name="proc", params=None):
    r = client.post("/api/scripts", json={"kind": kind, "name": name, "code": code, "params": params or {}})
    assert r.status_code == 201, r.json()
    return r.json()


def _custom_cfg(client, ds_id, script_id, params=None, checks=None):
    return config(client, ds_id, slots={"normalize": {"script_id": script_id, "params": params}},
                  checks=[] if checks is None else checks)


def _wait_status(client, run_id, status, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] == status:
            return body
        time.sleep(0.05)
    raise AssertionError(body)


def test_custom_code_disabled_in_safe_default_mode(client):
    ds = demo_dataset(client)
    s = _script(client, V1)
    cfg = _custom_cfg(client, ds["dataset_id"], s["script_id"])
    r = start_run(client, cfg["config_id"])
    assert r.status_code == 403 and r.json()["code"] == "CUSTOM_EXECUTION_DISABLED"
    assert client.get("/api/runs").json()["total"] == 0  # nothing started, no old procedure ran


def test_long_run_does_not_block_status_and_health(trusted):
    c = trusted
    ds = demo_dataset(c)
    s = _script(c, SLOW_NORMALIZE)
    cfg = _custom_cfg(c, ds["dataset_id"], s["script_id"], params={"sleep": 2.5})
    run = start_run(c, cfg["config_id"]).json()
    _wait_status(c, run["run_id"], "RUNNING")
    worst = 0.0
    for _ in range(10):
        t = time.monotonic()
        assert c.get("/health").status_code == 200
        assert c.get(f"/api/runs/{run['run_id']}").json()["status"] == "RUNNING"
        worst = max(worst, time.monotonic() - t)
        time.sleep(0.1)
    assert worst < 0.5, worst
    assert wait_run(c, run["run_id"])["status"] == "COMPLETED"


def test_procedure_crash_and_timeout_fail_run_with_safe_diagnostics(trusted, env, monkeypatch):
    c = trusted
    ds = demo_dataset(c)
    crash = _script(c, "def normalize(document, app_id, source, params):\n    raise RuntimeError('boom in user code')\n")
    run = start_run(c, _custom_cfg(c, ds["dataset_id"], crash["script_id"])["config_id"]).json()
    done = wait_run(c, run["run_id"])
    assert done["status"] == "FAILED" and done["error"]["code"] == "NORMALIZATION_ERROR"
    assert "boom in user code" in done["error"]["message"]
    events = c.get(f"/api/runs/{run['run_id']}/events").json()["items"]
    assert any(e["level"] == "ERROR" for e in events)
    assert str(env["home"]) not in json.dumps(events) and str(BACKEND_DIR) not in json.dumps(events)
    assert c.get("/health").status_code == 200


def test_timeout_kills_child_and_fails_run(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("DD_RUN_TIMEOUT_SECONDS", "6")
    with make_client() as c:
        ds = demo_dataset(c)
        s = _script(c, SLOW_NORMALIZE)
        cfg = _custom_cfg(c, ds["dataset_id"], s["script_id"], params={"sleep": 60})
        t = time.monotonic()
        done = wait_run(c, start_run(c, cfg["config_id"]).json()["run_id"], timeout=30)
        assert done["status"] == "FAILED" and done["error"]["code"] == "TIMEOUT"
        assert time.monotonic() - t < 15
        # the worker is free again
        cfg2 = config(c, ds["dataset_id"], checks=[])
        second = wait_run(c, start_run(c, cfg2["config_id"]).json()["run_id"])
        assert second["status"] == "COMPLETED", second["error"]


def test_worker_child_does_not_inherit_secrets(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("FAKE_INFRA_TOKEN", "s3cr3t-value")
    probe = V1 + """
import os
_leaks = [k for k in os.environ if k.startswith(('DD_', 'FAKE_')) or 'TOKEN' in k or 'KEY' in k]
if _leaks:
    raise RuntimeError('leaked env: %s' % _leaks)
"""
    with make_client() as c:
        ds = demo_dataset(c)
        s = _script(c, probe)
        done = wait_run(c, start_run(c, _custom_cfg(c, ds["dataset_id"], s["script_id"])["config_id"]).json()["run_id"])
        assert done["status"] == "COMPLETED", done
        assert "s3cr3t-value" not in json.dumps(c.get(f"/api/runs/{done['run_id']}/events").json())


def test_snapshot_is_immutable_and_next_run_uses_new_code(trusted):
    c = trusted
    ds = demo_dataset(c)
    blocker = _script(c, SLOW_NORMALIZE, name="blocker")
    s = _script(c, V1)
    cfg = _custom_cfg(c, ds["dataset_id"], s["script_id"])
    # occupy the single worker so run1 stays QUEUED while we edit the script
    b = start_run(c, _custom_cfg(c, ds["dataset_id"], blocker["script_id"], params={"sleep": 2})["config_id"]).json()
    _wait_status(c, b["run_id"], "RUNNING")
    run1 = start_run(c, cfg["config_id"]).json()
    assert c.get(f"/api/runs/{run1['run_id']}").json()["status"] == "QUEUED"
    assert c.put(f"/api/scripts/{s['script_id']}", json={"code": V2}).json()["revision"] == 2
    run2 = start_run(c, cfg["config_id"]).json()
    d1, d2 = wait_run(c, run1["run_id"]), wait_run(c, run2["run_id"])
    assert d1["status"] == d2["status"] == "COMPLETED"
    code1 = c.get(f"/api/runs/{run1['run_id']}/code/normalize").json()
    code2 = c.get(f"/api/runs/{run2['run_id']}/code/normalize").json()
    assert "VERSION = 1" in code1["code"] and code1["script_revision"] == 1
    assert "VERSION = 2" in code2["code"] and code2["script_revision"] == 2
    s1 = c.get(f"/api/runs/{run1['run_id']}/summary").json()
    s2 = c.get(f"/api/runs/{run2['run_id']}/summary").json()
    assert s2["rows"]["comparison"] < s1["rows"]["comparison"]  # new code really executed
    cfg_again = c.get(f"/api/configurations/{cfg['config_id']}").json()
    assert cfg_again == cfg


def test_log_output_is_capped(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("DD_MAX_LOG_BYTES", "4096")
    noisy = V1.replace("    return core_normalize", "    print('x' * 100000)\n    return core_normalize")
    with make_client() as c:
        ds = demo_dataset(c)
        s = _script(c, noisy)
        done = wait_run(c, start_run(c, _custom_cfg(c, ds["dataset_id"], s["script_id"])["config_id"]).json()["run_id"])
        assert done["status"] == "COMPLETED"
        log = env["home"] / "runs" / done["run_id"] / "pipeline.log"
        assert log.stat().st_size < 4096 + 200 and b"log truncated" in log.read_bytes()


def test_output_size_limit_fails_run(env, monkeypatch):
    monkeypatch.setenv("DD_MAX_OUTPUT_BYTES", "20000")
    with make_client() as c:
        ds = demo_dataset(c)
        done = wait_run(c, start_run(c, config(c, ds["dataset_id"], checks=[])["config_id"]).json()["run_id"])
        assert done["status"] == "FAILED" and done["error"]["code"] == "OUTPUT_LIMIT", done


def _spawn_worker(env_vars):
    return subprocess.Popen([sys.executable, "-m", "dd_backend", "worker"], env=env_vars,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def test_restart_marks_interrupted_and_keeps_queue(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("DD_EMBEDDED_WORKER", "0")
    monkeypatch.setenv("DD_WORKER_LEASE_SECONDS", "3")
    with make_client() as api:  # API only, external worker process
        ds = demo_dataset(api)
        slow = _script(api, SLOW_NORMALIZE)
        long_run = start_run(api, _custom_cfg(api, ds["dataset_id"], slow["script_id"], params={"sleep": 60})["config_id"]).json()
        queued = start_run(api, config(api, ds["dataset_id"], checks=[])["config_id"]).json()
        worker = _spawn_worker(dict(os.environ))
        try:
            _wait_status(api, long_run["run_id"], "RUNNING")
            os.killpg(worker.pid, signal.SIGKILL)  # crash: worker and (PDEATHSIG) its child die
            worker.wait()
            assert api.get(f"/api/runs/{long_run['run_id']}").json()["status"] == "RUNNING"  # stale until recovery
            assert api.get(f"/api/runs/{queued['run_id']}").json()["status"] == "QUEUED"
            ready = api.get("/ready").json()
            assert {c["name"]: c["ok"] for c in ready["checks"]}["worker"] is False
        finally:
            if worker.poll() is None:
                os.killpg(worker.pid, signal.SIGKILL)
        worker2 = _spawn_worker(dict(os.environ))
        try:
            failed = wait_run(api, long_run["run_id"])
            assert failed["status"] == "FAILED" and failed["error"]["code"] == "RUN_INTERRUPTED"
            assert failed["report_status"] == "FAILED"
            assert wait_run(api, queued["run_id"])["status"] == "COMPLETED"
            events = api.get(f"/api/runs/{long_run['run_id']}/events").json()["items"]
            assert events[-1]["level"] == "ERROR" and "RUN_INTERRUPTED" in events[-1]["message"]
        finally:
            os.killpg(worker2.pid, signal.SIGTERM)
            worker2.wait(timeout=30)


def test_graceful_shutdown_fails_running_job_explicitly(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    with make_client() as c:
        ds = demo_dataset(c)
        slow = _script(c, SLOW_NORMALIZE)
        run = start_run(c, _custom_cfg(c, ds["dataset_id"], slow["script_id"], params={"sleep": 60})["config_id"]).json()
        _wait_status(c, run["run_id"], "RUNNING")
    with make_client() as c2:
        c2.cookies = c.cookies
        body = c2.get(f"/api/runs/{run['run_id']}").json()
        assert body["status"] == "FAILED" and body["error"]["code"] == "RUN_INTERRUPTED"
