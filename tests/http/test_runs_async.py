"""Async Run 202 -> polling -> COMPLETED with the REAL core (api.md, execution.md, FR-003/014/015/017)."""
from __future__ import annotations

import json
import subprocess
import sys
import uuid

import pytest

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


FINAL_STATES = ("COMPLETED", "FAILED")


ORGANIZER_CHECK_IDS = {"ar_drop_by_product", "attribute_new_loss", "external_score_drift",
                       "stop_factor_disappeared", "target_model_changed"}
ROW_FIELDS = {"LABEL", "SOURCE", "ARGUMENT", "CNT", "TOTAL", "METRIC", "APP_IDS", "RESULT", "CONFIDENCE"}


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def row_problems(r, app_universe=None) -> list[str]:
    """CR5 #2: values, types and consistency of one organizer check row (S4/S5)."""
    import math

    if not (isinstance(r, dict) and ROW_FIELDS <= set(r)):
        return ["missing fields"]
    out = []
    if not (isinstance(r["LABEL"], str) and r["LABEL"]) or not isinstance(r["ARGUMENT"], str):
        out.append("LABEL/ARGUMENT not strings")
    if r["SOURCE"] not in ("BEFORE", "AFTER") or r["RESULT"] not in ("PASS", "FAIL") \
            or r["CONFIDENCE"] not in ("HIGH", "LOW"):
        out.append("enum value outside contract")
    cnt, total, metric, ids = r["CNT"], r["TOTAL"], r["METRIC"], r["APP_IDS"]
    if not (_is_int(cnt) and _is_int(total) and 0 <= cnt <= total):
        out.append("CNT/TOTAL not integers with 0 <= CNT <= TOTAL")
    if app_universe is not None and _is_int(total) and total > len(app_universe):
        out.append("TOTAL exceeds the number of applications in the Run")
    if not (isinstance(metric, (int, float)) and not isinstance(metric, bool) and math.isfinite(metric)):
        out.append("METRIC not a finite number")
    if not (isinstance(ids, list) and all(isinstance(x, str) and x for x in ids)
            and ids == sorted(set(ids)) and (not _is_int(cnt) or len(ids) <= cnt)):
        out.append("APP_IDS not a sorted unique list of strings with len <= CNT")
    elif app_universe is not None and not set(ids) <= app_universe:
        out.append("APP_IDS outside this Run")
    return out


def report_problems(body, run, expected_check_ids=ORGANIZER_CHECK_IDS, app_universe=None) -> list[str]:
    """Why `body` is NOT a complete, well-formed initial report of `run` with exactly the expected checks (CR3 #1).
    Empty list = valid. Validates identity, every execution record, every check row and their consistency."""
    if not isinstance(body, dict):
        return ["not an object"]
    problems = []
    for key, want in (("report_id", run["initial_report_id"]), ("run_id", run["run_id"]),
                      ("check_run_id", run["initial_check_run_id"]),
                      ("dataset_revision_id", run["dataset_revision_id"])):
        if body.get(key) != want:
            problems.append(f"{key}={body.get(key)!r} != {want!r}")
    if body.get("completeness") != "COMPLETE":
        problems.append(f"completeness={body.get('completeness')!r}")
    for key, kind in (("summary", dict), ("diagnostics", list), ("timings_seconds", dict)):
        if not isinstance(body.get(key), kind):
            problems.append(f"{key} missing or not a {kind.__name__}")
    if isinstance(body.get("diagnostics"), list) and body["diagnostics"]:
        problems.append(f"unexpected execution diagnostics {str(body['diagnostics'])[:120]}")
    executions, rows = body.get("executions"), body.get("checks")
    if not isinstance(executions, list) or not isinstance(rows, list):
        return problems + ["executions/checks are not lists"]
    ids = []
    for e in executions:
        if not (isinstance(e, dict) and isinstance(e.get("execution_id"), str) and e["execution_id"]
                and e.get("execution_status") == "SUCCEEDED" and isinstance(e.get("rows_count"), int)
                and e["rows_count"] >= 0):
            problems.append(f"bad execution record {str(e)[:120]}")
            continue
        ids.append(e.get("check_id"))
    if sorted(ids) != sorted(expected_check_ids):
        problems.append(f"executed checks {sorted(map(str, ids))} != expected {sorted(expected_check_ids)}")
    if sum(e["rows_count"] for e in executions if isinstance(e, dict) and isinstance(e.get("rows_count"), int)) \
            != len(rows):
        problems.append("sum(rows_count) != number of check rows")
    if not rows:
        problems.append("no check rows")
    for r in rows:
        problems += [f"{why}: {str(r)[:120]}" for why in row_problems(r, app_universe)]
    return problems


def test_not_ready_before_completion_and_status_stays_responsive(api_a, fixture_root):
    """FR-015/017, api.md: while a Run is not final, /summary answers 409 NOT_READY on EVERY observation and
    /checks answers 409 (or - known defect API-DISC-05 - an exact early copy of the initial report); health and
    status stay fast. Bounded by QA_RUN_TIMEOUT (CR2 #2); xfail only for the exact early-report condition after
    all independent completion assertions (CR2 #6)."""
    import os
    import time

    timeout = float(os.environ.get("QA_RUN_TIMEOUT", "300"))
    root, folder = fixture_root
    universe = {p.stem for p in (folder / "big" / "BEFORE").glob("*.json")}  # independent of the API
    ds = api_a.dataset(root, "dirs", "big/BEFORE", "big/AFTER")  # 400 pairs: a real running window
    run_id = api_a.start_run(api_a.config(ds["dataset_id"])["config_id"]).json()["run_id"]
    nonfinal_observations = 0
    early = []  # (stage, body) of /checks answering 200 while the Run was not final
    deadline = time.monotonic() + timeout
    run = {}
    while True:
        t0 = time.monotonic()
        run = api_a.get(f"/api/runs/{run_id}").json()
        assert api_a.get("/health").status_code == 200
        assert time.monotonic() - t0 < 2.0
        if run["status"] in FINAL_STATES:
            break
        assert time.monotonic() < deadline, (f"run not final after {timeout:.0f}s; last observed "
                                             f"status={run['status']} stage={run.get('stage')}")
        r = api_a.get(f"/api/runs/{run_id}/summary")
        after = api_a.get(f"/api/runs/{run_id}").json()
        if not (after["status"] in FINAL_STATES and r.status_code == 200):  # explicit completion race
            assert_envelope(r, 409, "NOT_READY")
            nonfinal_observations += 1
        c = api_a.get(f"/api/runs/{run_id}/checks")
        after = api_a.get(f"/api/runs/{run_id}").json()
        if c.status_code == 200 and after["status"] not in FINAL_STATES:
            early.append((after["stage"], c.json()))
        elif not (after["status"] in FINAL_STATES and c.status_code == 200):
            assert_envelope(c, 409, "NOT_READY")
        time.sleep(0.05)

    # Independent completion assertions run BEFORE any known-defect handling.
    assert run["status"] == "COMPLETED", (run["status"], run.get("stage"), run.get("error"))
    assert nonfinal_observations >= 2, ("no not-ready window was observed on a 400-pair run; the test cannot "
                                        "verify FR-017 - enlarge the dataset rather than skipping")
    assert api_a.get(f"/api/runs/{run_id}/summary").status_code == 200
    final_checks = api_a.get(f"/api/runs/{run_id}/checks")
    assert final_checks.status_code == 200, final_checks.text[:300]
    assert report_problems(final_checks.json(), run, app_universe=universe) == []

    # Every early 200 must be exactly the published initial report, else it is a real failure, not API-DISC-05.
    for stage, body in early:
        assert stage in ("CHECKING", "FINALIZING"), f"/checks answered 200 already in stage {stage}"
        assert report_problems(body, run, app_universe=universe) == [] and body == final_checks.json(), \
            (stage, str(body)[:300])
    known_defect(bool(early),
                 f"API-DISC-05: /runs/{{id}}/checks serves the (complete, correct) initial report while the Run is "
                 f"still {sorted({s for s, _ in early})}, before COMPLETED (FR-017, api.md not-ready)")


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
    """api.md: report data of a failed run -> explicit error, never an empty 'successful' table.
    CR3 #3: same early-rejection policy as test_invalid_json_fails_the_run. If the backend rejects the invalid
    input at registration or Run creation, no failed Run exists and this coverage is explicitly unavailable."""
    root, _ = fixture_root
    r = api_a.post("/api/datasets", {"name": "qa-badjson2", "root": root, "mode": "dirs",
                                     "before": "badjson/BEFORE", "after": "badjson/AFTER"}, key=None)
    if r.status_code != 201:
        assert_envelope(r, (409, 422))
        pytest.skip("backend rejects invalid input at registration: failed-Run publication coverage unavailable "
                    "- NOT VERIFIED")
    accepted = api_a.start_run(api_a.config(r.json()["dataset_id"])["config_id"])
    if accepted.status_code != 202:
        assert_envelope(accepted, (409, 422))
        pytest.skip("backend rejects invalid input at Run creation: failed-Run publication coverage unavailable "
                    "- NOT VERIFIED")
    final = api_a.wait(f"/api/runs/{accepted.json()['run_id']}")
    assert final["status"] == "FAILED", (final["status"], final["stage"], final["error"])
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
