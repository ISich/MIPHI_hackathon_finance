"""Review #4 (MAJOR): no overlapping execution on lease expiry; fenced publication."""
import os
import signal
import subprocess
import sys
import time

from conftest import make_client, wait_run
from helpers import config, demo_dataset, start_run

SLOW = """
import time
from decision_diff.core import normalize as core_normalize
from decision_diff.configs import REAL

def normalize(document, app_id, source, params):
    time.sleep(params.get('sleep', 0))
    return core_normalize(document, app_id, source, REAL)
"""


def _status(c, run_id):
    return c.get(f"/api/runs/{run_id}").json()


def test_paused_live_worker_keeps_its_job_and_no_second_job_overlaps(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("DD_EMBEDDED_WORKER", "0")
    monkeypatch.setenv("DD_WORKER_LEASE_SECONDS", "2")
    with make_client() as api:
        ds = demo_dataset(api)
        slow = api.post("/api/scripts", json={"kind": "normalize", "name": "slow", "code": SLOW}).json()
        long_cfg = config(api, ds["dataset_id"], checks=[], slots={"normalize": {"script_id": slow["script_id"], "params": {"sleep": 4}}})
        long_run = start_run(api, long_cfg["config_id"]).json()
        queued = start_run(api, config(api, ds["dataset_id"], checks=[])["config_id"]).json()
        w1 = subprocess.Popen([sys.executable, "-m", "dd_backend", "worker"], env=dict(os.environ),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        w2 = None
        try:
            deadline = time.time() + 30
            while _status(api, long_run["run_id"])["status"] != "RUNNING" and time.time() < deadline:
                time.sleep(0.05)
            os.kill(w1.pid, signal.SIGSTOP)          # alive but silent: heartbeat goes stale
            time.sleep(3)
            w2 = subprocess.Popen([sys.executable, "-m", "dd_backend", "worker"], env=dict(os.environ),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            time.sleep(4)
            assert _status(api, long_run["run_id"])["status"] == "RUNNING"   # not stolen
            assert _status(api, queued["run_id"])["status"] == "QUEUED"      # no overlapping execution
            os.kill(w1.pid, signal.SIGCONT)
            assert wait_run(api, long_run["run_id"])["status"] == "COMPLETED"
            assert wait_run(api, queued["run_id"])["status"] == "COMPLETED"
        finally:
            for w in (w1, w2):
                if w is not None and w.poll() is None:
                    os.killpg(w.pid, signal.SIGCONT)
                    os.killpg(w.pid, signal.SIGTERM)
                    w.wait(timeout=30)


def test_worker_that_lost_ownership_cannot_publish(env, monkeypatch):
    from dd_backend import worker as worker_mod
    original = worker_mod.Worker._run_checks

    def takeover_then_continue(self, run_id, cr_id, *, initial):
        # another worker declared us dead and failed the job in between
        with self.db.tx() as con:
            con.execute("UPDATE runs SET status='FAILED', error_code='RUN_INTERRUPTED', worker_id='wrk_other' WHERE run_id=?", (run_id,))
            con.execute("UPDATE check_runs SET status='FAILED', worker_id='wrk_other' WHERE check_run_id=?", (cr_id,))
            con.execute("UPDATE reports SET status='FAILED' WHERE check_run_id=?", (cr_id,))
        return original(self, run_id, cr_id, initial=initial)
    monkeypatch.setattr(worker_mod.Worker, "_run_checks", takeover_then_continue)
    with make_client() as c:
        ds = demo_dataset(c)
        run = start_run(c, config(c, ds["dataset_id"], checks=[])["config_id"]).json()
        time.sleep(0.5)
        final = wait_run(c, run["run_id"])
        time.sleep(1.0)
        final = _status(c, run["run_id"])
        assert final["status"] == "FAILED" and final["error"]["code"] == "RUN_INTERRUPTED", final
        assert final["report_status"] == "FAILED"
        events = c.get(f"/api/runs/{run['run_id']}/events").json()["items"]
        assert not any("COMPLETED" in e["message"] or "published" in e["message"] for e in events)
        monkeypatch.undo()
        ok = start_run(c, config(c, ds["dataset_id"], checks=[])["config_id"]).json()
        assert wait_run(c, ok["run_id"])["status"] == "COMPLETED"
