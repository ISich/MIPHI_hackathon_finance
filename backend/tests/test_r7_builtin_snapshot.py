"""Review #7 (MAJOR): built-in code that would execute must equal the accepted snapshot."""
import json

import pytest

from conftest import make_client, wait_run
from helpers import config, demo_dataset, start_run


@pytest.mark.parametrize("tamper", ["code_sha256", "core_commit"])
def test_runtime_differs_from_accepted_snapshot_is_refused(env, monkeypatch, tamper):
    monkeypatch.setenv("DD_EMBEDDED_WORKER", "0")
    with make_client() as api:
        ds = demo_dataset(api)
        run = start_run(api, config(api, ds["dataset_id"], checks=[])["config_id"]).json()
        cfg_path = env["home"] / "runs" / run["run_id"] / "snapshot" / "config.json"
        cfg = json.loads(cfg_path.read_text())
        # simulate "package upgraded while the run was queued"
        if tamper == "code_sha256":
            cfg["procedures"]["normalize"]["code_sha256"] = "0" * 64
        else:
            assert cfg["core"]["commit"]
            cfg["core"]["commit"] = "f" * 40
        cfg_path.write_text(json.dumps(cfg))
        monkeypatch.setenv("DD_EMBEDDED_WORKER", "1")
        with make_client(cookies=api.cookies) as c:
            done = wait_run(c, run["run_id"])
        assert done["status"] == "FAILED" and done["error"]["code"] == "CORE_VERSION_MISMATCH", done


def test_check_only_run_refuses_a_different_core_than_the_data_run(client, env):
    from conftest import wait_check_run
    from helpers import idem
    ds = demo_dataset(client)
    done = wait_run(client, start_run(client, config(client, ds["dataset_id"], checks=[])["config_id"]).json()["run_id"])
    cfg_path = env["home"] / "runs" / done["run_id"] / "snapshot" / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["core"]["commit"] = "e" * 40   # the data run was produced by another core
    cfg_path.write_text(json.dumps(cfg))
    check = next(s for s in client.get("/api/scripts?kind=check").json() if s["source"] == "builtin")
    cr = client.post(f"/api/runs/{done['run_id']}/check-runs", json={"checks": [{"script_id": check["script_id"]}]},
                     headers=idem()).json()
    final = wait_check_run(client, cr["check_run_id"])
    assert final["status"] == "FAILED" and final["error"]["code"] == "CORE_VERSION_MISMATCH", final
