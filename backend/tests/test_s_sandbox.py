"""Execution mode ``sandboxed``: user Python runs, but under Landlock + seccomp + rlimits.

Every test drives the real worker/children; escape attempts are made from inside user code.
"""
import json
import os
import subprocess
import sys

import pytest

from conftest import BACKEND_DIR, make_client, wait_check_run, wait_run
from helpers import config, demo_dataset, idem, start_run
from dd_backend import sandbox

pytestmark = pytest.mark.skipif(not sandbox.supported()[0], reason=sandbox.supported()[1])

# Each probe must raise inside the sandbox; the code returns {probe: "allowed" | "denied:<Exc>"}.
PROBES = r'''
import json, os, socket, subprocess, threading
from pathlib import Path

def _probes(secret_paths):
    res = {}
    def probe(name, fn):
        try:
            fn(); res[name] = "allowed"
        except Exception as e:
            res[name] = "denied:" + type(e).__name__
    for i, p in enumerate(secret_paths):
        probe(f"read_{i}", lambda p=p: Path(p).read_bytes())
        probe(f"list_{i}", lambda p=p: os.listdir(Path(p).parent))
    probe("write_home", lambda: Path(secret_paths[0]).with_name("planted.py").write_text("x"))
    probe("etc_passwd", lambda: Path("/etc/passwd").read_text())
    probe("proc_environ", lambda: Path(f"/proc/{os.getppid()}/environ").read_bytes())
    probe("tcp", lambda: socket.create_connection(("1.1.1.1", 443), timeout=1))
    probe("tcp_local", lambda: socket.create_connection(("127.0.0.1", 22), timeout=1))
    probe("udp", lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("8.8.8.8", 53)))
    probe("unix", lambda: socket.socket(socket.AF_UNIX).connect("/run/systemd/private"))
    probe("exec", lambda: subprocess.run(["/bin/sh", "-c", "true"], check=True))
    probe("os_system", lambda: (_ for _ in ()).throw(PermissionError()) if os.system("true") != 0 else None)
    probe("fork", lambda: os.fork() == 0 and os._exit(0))
    probe("kill_parent", lambda: os.kill(os.getppid(), 0))
    probe("kill_group", lambda: os.kill(0, 0))
    probe("symlink", lambda: os.symlink("/etc/passwd", "link"))
    return res
'''


@pytest.fixture
def sandboxed(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "sandboxed")
    monkeypatch.setenv("DD_CHECK_TIMEOUT_SECONDS", "20")
    with make_client() as c:
        yield c


def _secrets(env) -> list[str]:
    home = env["home"]
    return [str(home / "backend.sqlite3"), str(home / "pivot-signing.key"),
            str(env["core"] / "examples" / "I32554354.json"), str(BACKEND_DIR / "pyproject.toml")]


def test_selftest_denies_every_escape(tmp_path):
    res = sandbox.selftest(tmp_path)
    assert res["ok"], res
    assert all(v.startswith("denied") for k, v in res["probes"].items() if k not in sandbox.EXPECT_ALLOWED)


def test_mode_is_visible_and_custom_execution_enabled(sandboxed):
    assert sandboxed.get("/api/session").json()["execution_mode"] == "sandboxed"
    kinds = sandboxed.get("/api/script-kinds").json()
    assert all(k["custom_execution_enabled"] for k in kinds)
    ready = sandboxed.get("/ready").json()
    sb = next(c for c in ready["checks"] if c["name"] == "sandbox")
    assert sb["ok"] and ready["execution_mode"] == "sandboxed" and ready["warnings"]


def test_builtin_run_with_organizer_checks_still_works(sandboxed):
    ds = demo_dataset(sandboxed)
    done = wait_run(sandboxed, start_run(sandboxed, config(sandboxed, ds["dataset_id"])["config_id"]).json()["run_id"], 120)
    assert done["status"] == "COMPLETED", done
    report = sandboxed.get(f"/api/runs/{done['run_id']}/checks").json()
    assert {e["execution_status"] for e in report["executions"]} == {"SUCCEEDED"}
    events = sandboxed.get(f"/api/runs/{done['run_id']}/events").json()
    assert any("sandbox entered" in e["message"] for e in (events.get("items") or events))


def test_hostile_procedure_is_confined_but_runs(sandboxed, env):
    code = PROBES + f'''
from decision_diff.core import normalize as core_normalize
from decision_diff.configs import REAL
RESULT = _probes({_secrets(env)!r})
LEAKED = sorted(k for k, v in RESULT.items() if v == "allowed")

def normalize(document, app_id, source, params):
    if LEAKED:
        raise RuntimeError("SANDBOX LEAK: " + ",".join(LEAKED))
    return core_normalize(document, app_id, source, REAL)
'''
    s = sandboxed.post("/api/scripts", json={"kind": "normalize", "name": "hostile", "code": code, "params": {}}).json()
    ds = demo_dataset(sandboxed)
    cfg = config(sandboxed, ds["dataset_id"], slots={"normalize": {"script_id": s["script_id"]}}, checks=[])
    r = start_run(sandboxed, cfg["config_id"])
    assert r.status_code in (200, 201, 202), r.json()
    done = wait_run(sandboxed, r.json()["run_id"], 120)
    assert done["status"] == "COMPLETED", done
    assert not (env["home"] / "planted.py").exists()


def test_hostile_check_reports_all_denied(sandboxed, env):
    code = PROBES + f'''
def run(mart, params=None):
    res = _probes({_secrets(env)!r})
    leaked = sorted(k for k, v in res.items() if v == "allowed")
    return [{{"LABEL": "sandbox", "SOURCE": "AFTER", "ARGUMENT": json.dumps(res), "CNT": len(leaked), "TOTAL": len(res),
             "METRIC": 0.0, "APP_IDS": [], "RESULT": "FAIL" if leaked else "PASS", "CONFIDENCE": "HIGH"}}]

CHECK = {{"id": "sandbox_probe", "label": "sandbox probe", "params": {{}}, "entrypoint": run}}
'''
    sc = sandboxed.post("/api/scripts", json={"kind": "check", "name": "probe", "code": code}).json()
    ds = demo_dataset(sandboxed)
    cfg = config(sandboxed, ds["dataset_id"], checks=[{"script_id": sc["script_id"]}])
    done = wait_run(sandboxed, start_run(sandboxed, cfg["config_id"]).json()["run_id"], 120)
    report = sandboxed.get(f"/api/runs/{done['run_id']}/checks").json()
    ex = next(e for e in report["executions"] if e["check_id"] == "sandbox_probe")
    assert ex["execution_status"] == "SUCCEEDED", ex
    row = next(r for r in report["checks"] if r["LABEL"] == "sandbox")
    probes = json.loads(row["ARGUMENT"])
    assert row["RESULT"] == "PASS" and all(v.startswith("denied") for v in probes.values()), probes
    assert not (env["home"] / "planted.py").exists()


def test_requested_sandbox_that_cannot_be_entered_fails_closed(tmp_path):
    """A broken policy never degrades to unconfined execution: the child exits 71 before user code."""
    marker = tmp_path / "ran"
    code = ("from dd_backend import sandbox; sandbox.enter_from_env(); "
            f"open({str(marker)!r}, 'w').write('user code ran')")
    env = {"PATH": "/usr/bin:/bin", sandbox.POLICY_ENV: "{not json"}
    p = subprocess.run([sys.executable, "-I", "-c", code], env=env, capture_output=True, text=True)
    assert p.returncode == sandbox.EXIT_SANDBOX_FAILED and "SANDBOX_FAILED" in p.stderr
    assert not marker.exists()


def test_sandboxed_mode_may_be_published(env, monkeypatch):
    """Unlike trusted-local, sandboxed is allowed behind a public host name (it is the point of the mode)."""
    from dd_backend.settings import load_settings
    monkeypatch.setenv("DD_EXECUTION_MODE", "sandboxed")
    monkeypatch.setenv("DD_ALLOWED_HOSTS", "finance.example.org")
    s = load_settings()
    assert s.sandboxed and s.custom_execution_enabled


def test_policy_grants_only_own_run_paths(env, monkeypatch):
    from dd_backend.db import Database
    from dd_backend.settings import load_settings
    from dd_backend.worker import Worker
    monkeypatch.setenv("DD_EXECUTION_MODE", "sandboxed")
    s = load_settings()
    w = Worker(s, Database(s.db_path))
    pol = json.loads(w._sandbox_env([s.runs_dir / "r1" / "snapshot"], [s.runs_dir / "r1" / "work"], 10)[sandbox.POLICY_ENV])
    assert pol["ro"] == [str(s.runs_dir / "r1" / "snapshot")] and pol["rw"] == [str(s.runs_dir / "r1" / "work")]
    assert str(s.home) in pol["deny_under"] and pol["cpu_seconds"] == 11
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    assert Worker(load_settings(), Database(s.db_path))._sandbox_env([], [], 1) == {}
