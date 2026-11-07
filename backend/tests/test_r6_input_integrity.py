"""Review #6 (MAJOR): the run processes exactly the bytes it fingerprinted, inside the root."""
import json

from conftest import make_client, wait_run
from helpers import config, copy_pair_dirs, start_run

MUTATOR = """
import json
from decision_diff.core import normalize as core_normalize
from decision_diff.configs import REAL

def normalize(document, app_id, source, params):
    if app_id == 'T0000' and source == 'BEFORE':
        with open(params['target'], 'w') as f:
            f.write(params['content'])
    return core_normalize(document, app_id, source, REAL)
"""


def test_file_changed_during_processing_does_not_leak_into_the_run(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    root = copy_pair_dirs(env["core"], env["data"], n=2)
    before_t1 = (root / "BEFORE" / "T0001.json").read_text()
    with make_client() as c:
        ds = c.post("/api/datasets", json={"name": "d", "root": "data", "mode": "dirs",
                                           "before": "set1/BEFORE", "after": "set1/AFTER"}).json()
        s = c.post("/api/scripts", json={"kind": "normalize", "name": "mut", "code": MUTATOR}).json()
        cfg = config(c, ds["dataset_id"], checks=[], slots={"normalize": {"script_id": s["script_id"], "params": {
            "target": str(root / "AFTER" / "T0001.json"), "content": before_t1}}})
        done = wait_run(c, start_run(c, cfg["config_id"]).json()["run_id"])
        assert done["status"] == "COMPLETED", done
        summary = c.get(f"/api/runs/{done['run_id']}/summary").json()
        # Fingerprinted AFTER/T0001 changed the decision; the later on-disk rewrite (== BEFORE) must not be used.
        assert summary["decision_changed_apps"] == 2


def test_symlink_swapped_in_after_acceptance_is_refused(env, tmp_path, monkeypatch):
    root = copy_pair_dirs(env["core"], env["data"], n=1)
    target = root / "AFTER" / "T0000.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(target.read_bytes())  # identical bytes: fingerprint alone cannot notice
    monkeypatch.setenv("DD_EMBEDDED_WORKER", "0")
    with make_client() as api:
        ds = api.post("/api/datasets", json={"name": "d", "root": "data", "mode": "dirs",
                                             "before": "set1/BEFORE", "after": "set1/AFTER"}).json()
        run = start_run(api, config(api, ds["dataset_id"], checks=[])["config_id"]).json()
        assert run["status"] == "QUEUED"
        target.unlink()
        target.symlink_to(outside)              # swapped between acceptance and execution
        monkeypatch.setenv("DD_EMBEDDED_WORKER", "1")
        with make_client(cookies=api.cookies) as c:
            done = wait_run(c, run["run_id"])
        assert done["status"] == "FAILED" and done["error"]["code"] == "INPUT_ESCAPES_ROOT", done
        assert str(tmp_path) not in __import__("json").dumps(api.get(f"/api/runs/{run['run_id']}/events").json())
