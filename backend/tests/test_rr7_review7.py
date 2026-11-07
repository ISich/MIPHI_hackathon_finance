"""Codex re-review #7 (eb0053f): regression tests, written before the fixes."""
import time

from conftest import make_client, wait_check_run, wait_run
from helpers import config, demo_dataset, idem, start_run

SLOW_CHECK = """
import time

def run(mart, params=None):
    time.sleep(30)
    return []

CHECK = {'id': 'slow_last', 'label': 'slow', 'params': {}, 'entrypoint': run}
"""


# ------------------------------------------------------------------ #1 MAJOR
def test_shutdown_during_final_check_is_run_interrupted_not_completed(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    with make_client() as c:
        ds = demo_dataset(c)
        done = wait_run(c, start_run(c, config(c, ds["dataset_id"], checks=[])["config_id"]).json()["run_id"])
        sid = c.post("/api/scripts", json={"kind": "check", "name": "slow", "code": SLOW_CHECK}).json()["script_id"]
        cr = c.post(f"/api/runs/{done['run_id']}/check-runs", json={"checks": [{"script_id": sid}]}, headers=idem()).json()
        result = env["home"] / "runs" / done["run_id"] / "checks" / cr["check_run_id"] / "check-01.params.json"
        deadline = time.time() + 30
        while not result.exists() and time.time() < deadline:   # registration done, execution child running
            time.sleep(0.05)
        time.sleep(1.0)
        cookies = c.cookies
    # graceful stop of the embedded worker happened at context exit; restart on the same home
    with make_client(cookies=cookies) as c2:
        final = wait_check_run(c2, cr["check_run_id"])
        assert final["status"] == "FAILED" and final["error"]["code"] == "RUN_INTERRUPTED", final
        assert c2.get(f"/api/reports/{cr['report_id']}").json()["status"] == "FAILED"


# ------------------------------------------------------------------ #2 MINOR
FAILED_REGISTRATION = """
import atexit, json, sys

def _rewrite():
    with open(sys.argv[-1], 'w') as f:
        f.write(json.dumps({"ok": False, "status": "CONTRACT_ERROR", "error_type": "CheckContractError",
                            "message": "x" * 60000}))
atexit.register(_rewrite)

def run(mart, params=None):
    return []

CHECK = {'id': '%s', 'label': 'x', 'params': {}, 'entrypoint': run}
"""


def test_failed_registration_diagnostics_count_against_the_report_budget(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("DD_MAX_REPORT_BYTES", "150000")
    with make_client() as c:
        ds = demo_dataset(c)
        ids = [c.post("/api/scripts", json={"kind": "check", "name": f"f{i}", "code": FAILED_REGISTRATION % f"f{i}"}).json()["script_id"]
               for i in range(3)]
        done = wait_run(c, start_run(c, config(c, ds["dataset_id"], checks=[{"script_id": i} for i in ids])["config_id"]).json()["run_id"])
        rep = c.get(f"/api/runs/{done['run_id']}/checks").json()
        statuses = [e["execution_status"] for e in rep["executions"]]
        assert statuses == ["CONTRACT_ERROR", "CONTRACT_ERROR", "INVALID_OUTPUT"], statuses
        assert any(d.get("error_type") == "ReportBudgetExceeded" for d in rep["diagnostics"])
