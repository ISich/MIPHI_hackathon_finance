"""Restart persistence (BACKEND_NIGHT_TASK D, execution.md): a Run interrupted by a server crash must not stay
RUNNING forever and must not silently disappear.

Opt-in: QA_BACKEND_DIR=<backend checkout with .venv> (absolute or relative; resolved before use). The test starts
its OWN server (Popen, loopback, free port, temporary DD_HOME), SIGKILLs it mid-run, restarts it on the same DD_HOME
and polls. Only its own processes are signalled.
"""
from __future__ import annotations

import sys
import time

import httpx
import pytest

from support.backend_proc import backend_dir, free_port, start_backend
from support.fixtures import pair, write_dataset
from support.http_api import Api

pytestmark = [pytest.mark.slow,
              pytest.mark.skipif(backend_dir() is None, reason="QA_BACKEND_DIR not set - NOT VERIFIED")]


def test_interrupted_run_is_failed_or_recovered_after_restart(tmp_path):
    data = tmp_path / "data"
    write_dataset(data / "big", [pair(f"R{i:04d}") for i in range(400)])  # long enough to be killed mid-run
    home, port = tmp_path / "home", free_port()
    backend = start_backend(home, {"qa": data}, port=port)
    try:
        api = Api(backend.url)
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
    finally:
        backend.stop(sig_kill=True)
    backend = start_backend(home, {"qa": data}, port=port)
    try:
        with httpx.Client(base_url=backend.url, cookies=cookies) as c:
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
        backend.stop()
