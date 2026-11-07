"""Restart persistence (BACKEND_NIGHT_TASK D, execution.md): a Run interrupted by a server crash must not stay
RUNNING forever and must not silently disappear.

Opt-in: QA_BACKEND_DIR=<backend checkout with .venv>. The test starts its OWN server (Popen, loopback, own port and
temporary DD_HOME), SIGKILLs it mid-run, restarts it on the same DD_HOME and polls. Only its own processes are killed.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from support.fixtures import pair, write_dataset
from support.http_api import Api

BACKEND = os.environ.get("QA_BACKEND_DIR")
pytestmark = [pytest.mark.slow, pytest.mark.skipif(not BACKEND, reason="QA_BACKEND_DIR not set - NOT VERIFIED")]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(home: Path, data: Path, port: int, log: Path) -> subprocess.Popen:
    env = {k: v for k, v in os.environ.items() if not k.startswith("DD_")}
    env.update(PYTHONDONTWRITEBYTECODE="1", DD_HOME=str(home), DD_DATA_ROOTS=f"qa={data}",
               DD_EXECUTION_MODE="builtin-only", DD_EMBEDDED_WORKER="1", DD_WORKER_LEASE_SECONDS="3")
    checks = subprocess.run([str(Path(__file__).resolve().parents[2] / "scripts" / "fetch_core_checks.sh")],
                            capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
    env["DD_CHECKS_DIR"] = checks
    proc = subprocess.Popen([str(Path(BACKEND) / ".venv" / "bin" / "python"), "-m", "uvicorn",
                             "dd_backend.app:create_app", "--factory", "--host", "127.0.0.1", "--port", str(port),
                             "--app-dir", BACKEND], cwd=str(home.parent), env=env,
                            stdout=log.open("ab"), stderr=subprocess.STDOUT)
    for _ in range(100):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        if proc.poll() is not None:
            raise AssertionError(log.read_text())
        time.sleep(0.2)
    proc.kill()
    raise AssertionError("server did not start")


def test_interrupted_run_is_failed_or_recovered_after_restart(tmp_path):
    data = tmp_path / "data"
    write_dataset(data / "big", [pair(f"R{i:04d}") for i in range(400)])  # long enough to be killed mid-run
    home, port, log = tmp_path / "home", _free_port(), tmp_path / "server.log"
    proc = _start(home, data, port, log)
    try:
        api = Api(f"http://127.0.0.1:{port}")
        ds = api.dataset("qa", "dirs", "big/BEFORE", "big/AFTER")
        run_id = api.start_run(api.config(ds["dataset_id"])["config_id"]).json()["run_id"]
        before_kill_status = "QUEUED"
        for _ in range(300):
            before_kill_status = api.get(f"/api/runs/{run_id}").json()["status"]
            if before_kill_status != "QUEUED":
                break
            time.sleep(0.05)
        assert before_kill_status == "RUNNING", f"run was {before_kill_status} at kill time; enlarge the dataset"
        cookies = dict(api.http.cookies)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
    proc = _start(home, data, port, log)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", cookies=cookies) as c:
            deadline, body = time.monotonic() + 120, {}
            while time.monotonic() < deadline:
                r = c.get(f"/api/runs/{run_id}")
                assert r.status_code == 200, r.text  # run did not disappear; session survived restart
                body = r.json()
                if body["status"] in ("COMPLETED", "FAILED"):
                    break
                time.sleep(0.5)
            assert body["status"] in ("COMPLETED", "FAILED"), f"stuck after restart: {body}"
            if body["status"] == "FAILED":
                assert body["error"] and body["error"]["code"], body
            events = c.get(f"/api/runs/{run_id}/events").json()["items"]
            seqs = [e["seq"] for e in events]
            assert seqs == sorted(set(seqs))
            print(f"\nrestart outcome: {before_kill_status} -> {body['status']} {body.get('error')}", file=sys.stderr)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
