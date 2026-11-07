"""Async Run 202 -> polling -> COMPLETED with the REAL core (api.md, execution.md, FR-003/014/015/017)."""
from __future__ import annotations

import json
import subprocess
import sys
import uuid


from support.http_api import assert_envelope, known_defect

STAGES = ["VALIDATING", "NORMALIZING", "COMPARING", "AGGREGATING", "CHECKING", "FINALIZING"]


def test_accept_is_fast_202_with_identity_and_status_url(completed_example_run):
    acc = completed_example_run["accepted"]
    assert completed_example_run["accept_seconds"] < 5
    assert acc["status"] in ("QUEUED", "RUNNING", "COMPLETED")
    assert acc["run_id"] and acc["initial_report_id"] and acc["initial_check_run_id"]
    assert completed_example_run["location"] and acc["run_id"] in completed_example_run["location"]


def test_run_completes_with_status_separate_from_stage(completed_example_run):
    final = completed_example_run["final"]
    assert final["status"] == "COMPLETED", (final["status"], final["stage"], final["error"])
    assert final["error"] is None and final["finished_at"]
    assert final["stage"] in STAGES  # stage is its own field, not a status value


def test_events_monotonic_and_follow_stage_order(api_a, completed_example_run):
    run_id = completed_example_run["final"]["run_id"]
    items, after = [], 0
    for _ in range(50):
        page = api_a.get(f"/api/runs/{run_id}/events", params={"after": after}).json()
        if not page["items"]:
            break
        items += page["items"]
        after = page["next_after"]
    seqs = [e["seq"] for e in items]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs)) and seqs
    seen = [s for s in dict.fromkeys(e["stage"] for e in items if e["stage"])]
    assert seen == [s for s in STAGES if s in seen], seen
    assert {"VALIDATING", "NORMALIZING", "COMPARING", "AGGREGATING", "FINALIZING"} <= set(seen)
    tail = api_a.get(f"/api/runs/{run_id}/events", params={"after": seqs[-1]}).json()
    assert tail["items"] == []


def test_summary_comes_from_real_core(api_a, completed_example_run, organizer_checks_dir, tmp_path):
    """Compare server summary with an independent local run of the pinned core CLI on the same files."""
    run_id = completed_example_run["final"]["run_id"]
    r = api_a.get(f"/api/runs/{run_id}/summary")
    assert r.status_code == 200, r.text
    server = r.json()
    server = server.get("summary", server)
    ex = organizer_checks_dir.parent / "examples"
    out = tmp_path / "local-core"
    subprocess.run([sys.executable, "-m", "decision_diff.cli", "--before", str(ex / "I32554354_other.json"),
                    "--after", str(ex / "I32554354.json"), "--out", str(out)], check=True, capture_output=True)
    local = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    for key in ("total_apps", "changed_apps", "decision_changed_apps", "changed_attributes", "change_types"):
        assert server[key] == local[key], (key, server, local)


def test_code_snapshot_of_executed_procedure(api_a, completed_example_run):
    run_id = completed_example_run["final"]["run_id"]
    r = api_a.get(f"/api/runs/{run_id}/code/normalize")
    assert r.status_code == 200, r.text
    snap = r.json()
    assert snap["code"] and len(snap["code_sha256"]) == 64 and snap["kind"] == "normalize"


def test_artifacts_have_fingerprints_and_no_server_paths(api_a, completed_example_run):
    run_id = completed_example_run["final"]["run_id"]
    body = api_a.get(f"/api/runs/{run_id}/artifacts").json()
    assert body["items"]
    for art in body["items"]:
        assert len(art["sha256"]) == 64
        assert "/home/" not in json.dumps(art) and "/tmp/" not in json.dumps(art)


def test_run_listed_for_owner(api_a, completed_example_run):
    run_id = completed_example_run["final"]["run_id"]
    page = api_a.get("/api/runs", params={"limit": 200}).json()
    assert run_id in {r["run_id"] for r in page["items"]} and page["total"] >= 1


def test_idempotent_replay_and_key_reuse(api_a, completed_example_run):
    cfg = completed_example_run["config"]["config_id"]
    key = uuid.uuid4().hex
    first = api_a.post("/api/runs", {"configuration_id": cfg}, key=key)
    again = api_a.post("/api/runs", {"configuration_id": cfg}, key=key)
    assert first.status_code == again.status_code == 202
    assert first.json()["run_id"] == again.json()["run_id"]
    assert again.headers.get("idempotent-replay") == "true"
    other_ds = api_a.dataset("examples", "files", "I32554354.json", "I32554354_other.json")
    other_cfg = api_a.config(other_ds["dataset_id"])["config_id"]
    assert_envelope(api_a.post("/api/runs", {"configuration_id": other_cfg}, key=key), 409)
    api_a.wait(f"/api/runs/{first.json()['run_id']}")


def test_post_run_without_idempotency_key_is_explicit_error(api_a, completed_example_run):
    cfg = completed_example_run["config"]["config_id"]
    assert_envelope(api_a.post("/api/runs", {"configuration_id": cfg}, key=None), 400)


def test_not_ready_before_completion_and_status_stays_responsive(api_a, fixture_root):
    """FR-015/017, api.md: while a Run is not final, /summary AND /checks answer 409 NOT_READY on EVERY
    observation (never 200 data, never 5xx); health/status stay fast. CR #7: no silent skip."""
    import time

    root, _ = fixture_root
    ds = api_a.dataset(root, "dirs", "big/BEFORE", "big/AFTER")  # 400 pairs: a real running window
    run_id = api_a.start_run(api_a.config(ds["dataset_id"])["config_id"]).json()["run_id"]
    nonfinal_observations = 0
    early_checks = []  # /checks answered 200 while the Run was not final (stage recorded)
    while True:
        t0 = time.monotonic()
        run = api_a.get(f"/api/runs/{run_id}").json()
        status = run["status"]
        assert api_a.get("/health").status_code == 200
        assert time.monotonic() - t0 < 2.0
        if status in ("COMPLETED", "FAILED"):
            break
        r = api_a.get(f"/api/runs/{run_id}/summary")
        after = api_a.get(f"/api/runs/{run_id}").json()
        if not (after["status"] in ("COMPLETED", "FAILED") and r.status_code == 200):  # explicit race
            assert_envelope(r, 409, "NOT_READY")
            nonfinal_observations += 1
        c = api_a.get(f"/api/runs/{run_id}/checks")
        after = api_a.get(f"/api/runs/{run_id}").json()
        if c.status_code == 200 and after["status"] not in ("COMPLETED", "FAILED"):
            early_checks.append(after["stage"])
        elif not (after["status"] in ("COMPLETED", "FAILED") and c.status_code == 200):
            assert_envelope(c, 409, "NOT_READY")
        time.sleep(0.05)
    assert status == "COMPLETED"
    assert nonfinal_observations >= 2, ("no not-ready window was observed on a 400-pair run; the test cannot "
                                        "verify FR-017 - enlarge the dataset rather than skipping")
    assert api_a.get(f"/api/runs/{run_id}/summary").status_code == 200
    known_defect(bool(early_checks) and set(early_checks) <= {"CHECKING", "FINALIZING"},
                 f"API-DISC-05: /runs/{{id}}/checks serves the initial report (200) while the Run is still "
                 f"{sorted(set(early_checks))}, before COMPLETED (FR-017, api.md not-ready)")
    assert early_checks == [], early_checks
    assert api_a.get(f"/api/runs/{run_id}/checks").status_code == 200


def test_missing_pair_and_invalid_json_fail_the_run(api_a, fixture_root):
    """AC-02: broken input -> FAILED with diagnostics, no 'complete' report published."""
    root, _ = fixture_root
    r = api_a.post("/api/datasets", {"name": "qa-broken", "root": root, "mode": "dirs",
                                     "before": "broken/BEFORE", "after": "broken/AFTER"}, key=None)
    if r.status_code != 201:  # rejected at registration: acceptable explicit diagnostics
        assert_envelope(r, (409, 422))
        return
    ds = r.json()
    assert ds["revisions"][-1]["missing_after"] == ["K02"] or ds["revisions"][-1]["missing_after"] == ["K02.json"]
    cfg = api_a.config(ds["dataset_id"])
    accepted = api_a.start_run(cfg["config_id"])
    if accepted.status_code != 202:
        assert_envelope(accepted, (409, 422))
        return
    final = api_a.wait(f"/api/runs/{accepted.json()['run_id']}")
    assert final["status"] == "FAILED" and final["error"] and final["error"]["code"]
    rep = api_a.get(f"/api/reports/{final['initial_report_id']}").json()
    assert rep["status"] != "PUBLISHED" or rep["completeness"] != "COMPLETE"


def test_invalid_json_fails_the_run(api_a, fixture_root):
    """AC-02: every pair present but one invalid JSON -> FAILED, not a report on the remaining pairs."""
    root, _ = fixture_root
    r = api_a.post("/api/datasets", {"name": "qa-badjson", "root": root, "mode": "dirs",
                                     "before": "badjson/BEFORE", "after": "badjson/AFTER"}, key=None)
    if r.status_code != 201:
        assert_envelope(r, (409, 422))
        return
    accepted = api_a.start_run(api_a.config(r.json()["dataset_id"])["config_id"])
    if accepted.status_code != 202:
        assert_envelope(accepted, (409, 422))
        return
    final = api_a.wait(f"/api/runs/{accepted.json()['run_id']}")
    assert final["status"] == "FAILED" and final["error"]["code"], final
    assert api_a.get(f"/api/runs/{final['run_id']}/summary").status_code in (404, 409)
    rep = api_a.get(f"/api/reports/{final['initial_report_id']}").json()
    assert rep["status"] != "PUBLISHED"


def test_failed_run_report_data_is_not_served_as_success(api_a, fixture_root):
    """api.md: report data before ready / of a failed run -> explicit error, never an empty 'successful' table."""
    root, _ = fixture_root
    r = api_a.post("/api/datasets", {"name": "qa-badjson2", "root": root, "mode": "dirs",
                                     "before": "badjson/BEFORE", "after": "badjson/AFTER"}, key=None)
    assert r.status_code == 201, r.text
    final = api_a.wait(f"/api/runs/{api_a.start_run(api_a.config(r.json()['dataset_id'])['config_id']).json()['run_id']}")
    assert final["status"] == "FAILED"
    rep = final["initial_report_id"]
    for url in (f"/api/reports/{rep}/checks", f"/api/reports/{rep}/checks.html", f"/api/runs/{final['run_id']}/checks"):
        assert_envelope(api_a.get(url), (404, 409, 410, 422))


def test_technical_run_without_checks_is_marked(api_a, examples_root):
    """checks=[] is allowed as a technical run but must say NO_CHECKS_SELECTED, not 'all checks passed'."""
    ds = api_a.dataset(examples_root, "files", "I32554354_other.json", "I32554354.json")
    final = api_a.wait(f"/api/runs/{api_a.start_run(api_a.config(ds['dataset_id'], checks=[])['config_id']).json()['run_id']}")
    assert final["status"] == "COMPLETED"
    doc = api_a.get(f"/api/runs/{final['run_id']}/checks").json()
    assert doc["completeness"] == "NO_CHECKS_SELECTED" and doc["checks"] == []


def test_unknown_code_slot_and_bad_paging(api_a, completed_example_run):
    run_id = completed_example_run["final"]["run_id"]
    assert_envelope(api_a.get(f"/api/runs/{run_id}/code/nosuchslot"), (404, 422))
    assert_envelope(api_a.get("/api/runs", params={"limit": 100000}), 422)
    assert_envelope(api_a.get(f"/api/runs/{run_id}/events", params={"after": -1}), 422)
