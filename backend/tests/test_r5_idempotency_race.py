"""Review #5 (MAJOR): idempotency decided atomically inside the write transaction."""
import threading
import time

from conftest import peer, wait_check_run, wait_run
from helpers import config, demo_dataset, start_run


def _slow_snapshots(monkeypatch):
    from dd_backend import runs as runs_mod
    original = runs_mod.RunService._snapshot_checks

    def slow(self, *a, **k):
        out = original(self, *a, **k)
        time.sleep(0.6)  # widen the race window between pre-check and insert
        return out
    monkeypatch.setattr(runs_mod.RunService, "_snapshot_checks", slow)


def _parallel(fns):
    results = [None] * len(fns)
    barrier = threading.Barrier(len(fns))

    def go(i, fn):
        barrier.wait()
        results[i] = fn()
    threads = [threading.Thread(target=go, args=(i, f)) for i, f in enumerate(fns)]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    return results


def test_same_key_different_bodies_concurrently_gives_one_run_and_409(client, monkeypatch):
    ds = demo_dataset(client)
    c1 = config(client, ds["dataset_id"], checks=[])
    c2 = config(client, ds["dataset_id"], checks=[])
    _slow_snapshots(monkeypatch)
    clients = [peer(client.app, cookies=client.cookies) for _ in range(2)]
    key = {"Idempotency-Key": "race-1"}
    r1, r2 = _parallel([lambda: start_run(clients[0], c1["config_id"], key), lambda: start_run(clients[1], c2["config_id"], key)])
    codes = sorted([r1.status_code, r2.status_code])
    assert codes == [202, 409], (r1.json(), r2.json())
    loser = r1 if r1.status_code == 409 else r2
    assert loser.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert client.get("/api/runs").json()["total"] == 1
    winner = r1 if r1.status_code == 202 else r2
    wait_run(client, winner.json()["run_id"])
    run_dirs = [p.name for p in (client.app.state.settings.runs_dir).iterdir()]
    assert run_dirs == [winner.json()["run_id"]]  # loser's snapshot directory cleaned up


def test_identical_concurrent_check_runs_replay_without_500(client, monkeypatch):
    ds = demo_dataset(client)
    done = wait_run(client, start_run(client, config(client, ds["dataset_id"], checks=[])["config_id"]).json()["run_id"])
    check = next(s for s in client.get("/api/scripts?kind=check").json() if s["source"] == "builtin")
    body = {"checks": [{"script_id": check["script_id"]}]}
    _slow_snapshots(monkeypatch)
    clients = [peer(client.app, cookies=client.cookies) for _ in range(3)]
    url = f"/api/runs/{done['run_id']}/check-runs"
    res = _parallel([lambda c=c: c.post(url, json=body, headers={"Idempotency-Key": "race-cr"}) for c in clients])
    assert [r.status_code for r in res] == [202, 202, 202], [r.text for r in res]
    ids = {r.json()["check_run_id"] for r in res}
    assert len(ids) == 1
    accepted = ids.pop()
    wait_check_run(client, accepted)
    assert len(client.get(f"/api/runs/{done['run_id']}/reports").json()["items"]) == 2
    snap = client.app.state.settings.runs_dir / done["run_id"] / "snapshot" / "checks"
    assert [p.name for p in snap.iterdir()] == [accepted]  # initial run had no checks; losers left no orphans
