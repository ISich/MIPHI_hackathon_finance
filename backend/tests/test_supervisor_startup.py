"""A stop immediately after exec must not kill an uninitialized supervisor."""
import os
import signal

import pytest

from dd_backend.db import Database
from dd_backend.settings import load_settings
from dd_backend.worker import Worker
import dd_backend.worker as worker_module


@pytest.mark.parametrize("stop_signal", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_stop_before_supervisor_initialization_is_contained(env, tmp_path, monkeypatch, stop_signal):
    settings = load_settings()
    worker = Worker(settings, Database(settings.db_path))
    executed = tmp_path / "unexpected-child"
    original_popen = worker_module.subprocess.Popen
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())

    def launch_then_stop(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        # Real subprocess, deliberately stopped before Python installs its handlers.
        os.kill(child.pid, stop_signal)
        return child

    monkeypatch.setattr(worker_module.subprocess, "Popen", launch_then_stop)
    rc, timed_out = worker.spawn(
        ["timeit", "-n", "1", "-r", "1", f"open({str(executed)!r}, 'w').write('ran')"],
        workdir=tmp_path / "work", timeout=10, log_path=tmp_path / "execution.log",
    )
    assert rc == 137 and timed_out is False
    assert not executed.exists(), "a pending stop must prevent user-code startup"
    assert len(list((settings.home / "executions").glob("*.contained"))) == 1
    assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == previous_mask


def test_shutdown_releases_interrupted_job_and_preserves_queued_run(env, monkeypatch):
    from conftest import make_client, wait_run
    from helpers import config, demo_dataset, start_run
    import time

    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    with make_client() as client:
        dataset = demo_dataset(client)
        script = client.post("/api/scripts", json={
            "kind": "normalize", "name": "slow startup",
            "code": "import time\nfrom decision_diff.core import normalize as core_normalize\nfrom decision_diff.configs import REAL\ndef normalize(document, app_id, source, params):\n    time.sleep(60)\n    return core_normalize(document, app_id, source, REAL)\n",
        })
        assert script.status_code == 201, script.text
        slow = config(client, dataset["dataset_id"], checks=[], slots={
            "normalize": {"script_id": script.json()["script_id"]},
        })
        first = start_run(client, slow["config_id"]).json()["run_id"]
        deadline = time.monotonic() + 10
        while client.get(f"/api/runs/{first}").json()["status"] != "RUNNING":
            assert time.monotonic() < deadline, "worker did not claim the slow run"
            time.sleep(0.01)
        queued = start_run(client, config(client, dataset["dataset_id"], checks=[])["config_id"])
        assert queued.status_code == 202, queued.text
        second = queued.json()["run_id"]
        assert client.get(f"/api/runs/{second}").json()["status"] == "QUEUED"
    with make_client() as restarted:
        restarted.cookies = client.cookies
        interrupted = restarted.get(f"/api/runs/{first}").json()
        assert interrupted["status"] == "FAILED"
        assert interrupted["error"]["code"] == "RUN_INTERRUPTED"
        assert wait_run(restarted, second)["status"] == "COMPLETED"
