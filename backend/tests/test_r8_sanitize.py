"""Review #8 (MINOR): diagnostics never disclose absolute paths of data roots / checks dir."""
import json

from conftest import make_client, wait_run
from helpers import config, demo_dataset, start_run

OPENER = """
def normalize(document, app_id, source, params):
    open(params['path'])
"""


def test_error_mentioning_a_data_root_path_is_sanitized(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    with make_client() as c:
        ds = demo_dataset(c)
        s = c.post("/api/scripts", json={"kind": "normalize", "name": "o", "code": OPENER}).json()
        missing = str(env["data"] / "secret-area" / "missing.json")
        cfg = config(c, ds["dataset_id"], checks=[], slots={"normalize": {"script_id": s["script_id"], "params": {"path": missing}}})
        done = wait_run(c, start_run(c, cfg["config_id"]).json()["run_id"])
        assert done["status"] == "FAILED"
        blob = json.dumps(done) + json.dumps(c.get(f"/api/runs/{done['run_id']}/events").json())
        assert str(env["data"]) not in blob and str(env["core"]) not in blob
        assert "<root:data>" in blob
