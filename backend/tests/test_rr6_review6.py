"""Codex re-review #6 (570aa29): three MINOR regressions, written before the fixes."""
import threading
import time

from conftest import make_client, peer, wait_run
from helpers import config, demo_dataset, start_run


# ------------------------------------------------------------------ #1 registration params in budget
PADDED = """
def run(mart, params=None):
    return []

CHECK = {'id': '%s', 'label': 'pad', 'params': {'pad': 'x' * 60000}, 'entrypoint': run}
"""


def test_registration_metadata_counts_against_the_report_budget(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("DD_MAX_REPORT_BYTES", "150000")
    with make_client() as c:
        ds = demo_dataset(c)
        ids = [c.post("/api/scripts", json={"kind": "check", "name": f"p{i}", "code": PADDED % f"pad_{i}"}).json()["script_id"]
               for i in range(3)]
        done = wait_run(c, start_run(c, config(c, ds["dataset_id"], checks=[{"script_id": i} for i in ids])["config_id"]).json()["run_id"])
        rep = c.get(f"/api/runs/{done['run_id']}/checks").json()
        statuses = [e["execution_status"] for e in rep["executions"]]
        assert statuses == ["SUCCEEDED", "SUCCEEDED", "INVALID_OUTPUT"], statuses
        assert any(d.get("error_type") == "ReportBudgetExceeded" for d in rep["diagnostics"])
        assert rep["completeness"] == "INCOMPLETE"


# ------------------------------------------------------------------ #2 foreign APP_IDS in final bytes
FOREIGN_REWRITE = """
import atexit, json, sys

def _rewrite():
    row = {"LABEL": "x", "SOURCE": "AFTER", "ARGUMENT": "", "CNT": 1, "TOTAL": 1, "METRIC": 1,
           "APP_IDS": ["NOT_IN_RUN"], "RESULT": "PASS", "CONFIDENCE": "HIGH"}
    with open(sys.argv[-1], "w") as f:
        f.write(json.dumps({"status": "SUCCEEDED", "rows": [row], "diagnostics": []}))

def run(mart, params=None):
    atexit.register(_rewrite)
    return []

CHECK = {'id': 'foreign_rewrite', 'label': 'x', 'params': {}, 'entrypoint': run}
"""


def test_rewritten_result_with_foreign_app_ids_is_invalid_output(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    with make_client() as c:
        ds = demo_dataset(c)
        sid = c.post("/api/scripts", json={"kind": "check", "name": "f", "code": FOREIGN_REWRITE}).json()["script_id"]
        done = wait_run(c, start_run(c, config(c, ds["dataset_id"], checks=[{"script_id": sid}])["config_id"]).json()["run_id"])
        rep = c.get(f"/api/runs/{done['run_id']}/checks").json()
        assert rep["executions"][0]["execution_status"] == "INVALID_OUTPUT"
        assert rep["checks"] == [] and rep["completeness"] == "INCOMPLETE"


# ------------------------------------------------------------------ #3 concurrent PUT script
def test_concurrent_script_updates_get_distinct_revisions_or_conflict(client, monkeypatch):
    sid = client.post("/api/scripts", json={"kind": "check", "name": "s", "code": "x = 1\n"}).json()["script_id"]
    from dd_backend import registry as reg_mod
    real_validate = reg_mod.Registry._validate_code

    def slow_validate(self, kind, code):
        real_validate(self, kind, code)
        time.sleep(0.4)  # both requests have read revision 1 before either writes
    monkeypatch.setattr(reg_mod.Registry, "_validate_code", slow_validate)
    clients = [peer(client.app, cookies=client.cookies) for _ in range(2)]
    results = [None, None]
    barrier = threading.Barrier(2)

    def go(i):
        barrier.wait()
        results[i] = clients[i].put(f"/api/scripts/{sid}", json={"code": f"x = {i + 10}\n"})
    ts = [threading.Thread(target=go, args=(i,)) for i in range(2)]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    ok = [r for r in results if r.status_code == 200]
    conflicts = [r for r in results if r.status_code == 409]
    assert len(ok) + len(conflicts) == 2, [r.text for r in results]
    assert all(r.json()["code"] == "SCRIPT_CONFLICT" for r in conflicts)
    revisions = [r.json()["revision"] for r in ok]
    assert len(set(revisions)) == len(revisions), revisions          # never two successes with one revision
    final = client.get(f"/api/scripts/{sid}").json()
    assert final["revision"] == 1 + len(ok)
    winner = max(ok, key=lambda r: r.json()["revision"]).json()
    assert final["code"] == winner["code"]
