"""Slice C: real asynchronous Run through the single worker and the real decision_diff core."""
import csv
import io
import json
import time

from conftest import wait_run
from helpers import config, demo_dataset, idem, start_run


def test_real_fixture_run_end_to_end(client, env):
    ds = demo_dataset(client)
    cfg = config(client, ds["dataset_id"])
    t0 = time.monotonic()
    r = start_run(client, cfg["config_id"])
    assert r.status_code == 202, r.json()
    assert time.monotonic() - t0 < 2.0
    run = r.json()
    assert run["status"] == "QUEUED" and r.headers["location"] == f"/api/runs/{run['run_id']}"
    done = wait_run(client, run["run_id"])
    assert done["status"] == "COMPLETED", done
    assert done["stage"] == "FINALIZING" and done["checks_completeness"] == "COMPLETE"

    events = client.get(f"/api/runs/{run['run_id']}/events").json()["items"]
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(1, len(seqs) + 1))
    stages = []
    for e in events:
        label = e["stage"] + ("/" + e["substep"] if e["substep"] else "") if e["stage"] else None
        if label and (not stages or stages[-1] != label):
            stages.append(label)
    assert stages == ["VALIDATING", "NORMALIZING", "COMPARING", "COMPARING/SEGMENTS", "AGGREGATING", "CHECKING", "FINALIZING"]
    after = client.get(f"/api/runs/{run['run_id']}/events?after={seqs[2]}").json()["items"]
    assert after[0]["seq"] == seqs[3]

    summary = client.get(f"/api/runs/{run['run_id']}/summary").json()
    # Cross-check against the core CLI computed independently on the same files.
    from decision_diff.cli import load
    from decision_diff.configs import REAL
    from decision_diff.core import normalize_pair
    from decision_diff.reporting import summarize
    from decision_diff.segments import build_segment
    b = load(env["core"] / "examples" / "I32554354_other.json")
    a = load(env["core"] / "examples" / "I32554354.json")
    union, diff = normalize_pair(b, a, "I32554354", REAL)
    expected = summarize(diff, [build_segment(b, a, "I32554354")])
    for key, value in expected.items():
        assert summary[key] == value, key
    assert summary["rows"]["comparison"] == len(diff) and summary["rows"]["normalized_union"] == len(union)

    arts = {a["kind"]: a for a in client.get(f"/api/runs/{run['run_id']}/artifacts").json()["items"]}
    assert set(arts) == {"normalized_union", "comparison", "segments", "pivot_facts", "summary", "mart"}
    body = client.get(arts["comparison"]["download"]).content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(body), delimiter=";"))
    assert len(rows) == len(diff) and rows[0]["APP_ID"] == "I32554354"

    code = client.get(f"/api/runs/{run['run_id']}/code/normalize").json()
    assert code["source"] == "builtin" and "def normalize" in code["code"] and code["params"] == {"config": "real"}

    app = client.get(f"/api/runs/{run['run_id']}/applications/I32554354").json()
    assert app["segment"]["DECISION_CHANGED"] == 1 and len(app["comparison"]) == len(diff)
    facts = client.get(f"/api/runs/{run['run_id']}/pivot-facts?limit=5").json()
    assert len(facts["items"]) == 5 and facts["next_offset"] == 5
    drill = client.post(f"/api/runs/{run['run_id']}/pivot-facts/applications",
                        json={"group": {"SOURCE": "AFTER", "PATH": "decisionResult.decision"}}).json()
    assert drill["items"] == ["I32554354"]
    pivot = client.post(f"/api/runs/{run['run_id']}/pivot", json={"dimensions": ["DECISION_CHANGED"]}).json()
    assert [(str(i["dimensions"]["DECISION_CHANGED"]), i["cnt"]) for i in pivot["items"]] == [("1", 1)]


def test_summary_before_completion_is_not_ready(no_worker_client):
    c = no_worker_client
    ds = demo_dataset(c)
    run = start_run(c, config(c, ds["dataset_id"])["config_id"]).json()
    assert c.get(f"/api/runs/{run['run_id']}").json()["status"] == "QUEUED"
    for url in ("summary", "artifacts", "pivot-facts", "applications/I32554354"):
        r = c.get(f"/api/runs/{run['run_id']}/{url}")
        assert r.status_code == 409 and r.json()["code"] == "NOT_READY", url


def test_runs_list_and_idempotency(client):
    ds = demo_dataset(client)
    cfg = config(client, ds["dataset_id"], checks=[])
    h = idem()
    r1 = start_run(client, cfg["config_id"], h)
    r2 = start_run(client, cfg["config_id"], h)
    assert r1.status_code == r2.status_code == 202
    assert r1.json()["run_id"] == r2.json()["run_id"] and r2.headers["idempotent-replay"] == "true"
    other = client.post("/api/configurations", json={"name": "c2", "dataset_id": ds["dataset_id"]}).json()
    r3 = start_run(client, other["config_id"], h)
    assert r3.status_code == 409 and r3.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    r4 = client.post("/api/runs", json={"configuration_id": cfg["config_id"]})
    assert r4.status_code == 400 and r4.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    listed = client.get("/api/runs").json()
    assert listed["total"] == 1
    done = wait_run(client, r1.json()["run_id"])
    assert done["status"] == "COMPLETED" and done["checks_completeness"] == "NO_CHECKS_SELECTED"


def test_invalid_json_and_missing_pair_fail_the_run(client, env):
    from helpers import copy_pair_dirs
    root = copy_pair_dirs(env["core"], env["data"], n=2)
    (root / "AFTER" / "T0001.json").write_text("{broken")
    ds = client.post("/api/datasets", json={"name": "bad", "root": "data", "mode": "dirs",
                                            "before": "set1/BEFORE", "after": "set1/AFTER"}).json()
    run = start_run(client, config(client, ds["dataset_id"], checks=[])["config_id"]).json()
    done = wait_run(client, run["run_id"])
    assert done["status"] == "FAILED" and done["error"]["code"] == "INPUT_INVALID_JSON"
    assert "T0001.json" in done["error"]["message"] and str(env["data"]) not in json.dumps(done)
    assert client.get(f"/api/runs/{run['run_id']}/summary").status_code == 409

    root2 = copy_pair_dirs(env["core"], env["data"], name="set3", n=2)
    (root2 / "AFTER" / "T0001.json").unlink()
    ds2 = client.post("/api/datasets", json={"name": "unpaired", "root": "data", "mode": "dirs",
                                             "before": "set3/BEFORE", "after": "set3/AFTER"}).json()
    run2 = start_run(client, config(client, ds2["dataset_id"], checks=[])["config_id"]).json()
    done2 = wait_run(client, run2["run_id"])
    assert done2["status"] == "FAILED" and done2["error"]["code"] == "INPUT_MISSING_PAIR"
    assert client.get("/health").status_code == 200


def test_changed_files_after_registration_fail_with_revision_mismatch(client, env):
    from helpers import copy_pair_dirs
    root = copy_pair_dirs(env["core"], env["data"], n=1)
    ds = client.post("/api/datasets", json={"name": "d", "root": "data", "mode": "dirs",
                                            "before": "set1/BEFORE", "after": "set1/AFTER"}).json()
    cfg = config(client, ds["dataset_id"], checks=[])
    (root / "AFTER" / "T0000.json").write_text(json.dumps({"changed": True}))
    done = wait_run(client, start_run(client, cfg["config_id"]).json()["run_id"])
    assert done["status"] == "FAILED" and done["error"]["code"] == "DATASET_REVISION_MISMATCH"
