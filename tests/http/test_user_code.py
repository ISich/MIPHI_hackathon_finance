"""User code channels (FR-007, FR-008, FR-018, FR-019, FR-023, AC-13). Positive paths need trusted-local."""
from __future__ import annotations

import pytest

from support.http_api import assert_envelope, known_defect

KINDS = ("normalize", "compare", "segments", "aggregate", "check")

NEW_CHECK = '''
def run(mart, params=None):
    p = {**DEFAULTS, **(params or {})}
    lost = mart.app_ids(change_type="ATTRIBUTE_LOST")
    return [{"LABEL": CHECK["label"], "SOURCE": "AFTER", "ARGUMENT": "lost attrs", "CNT": len(lost),
             "TOTAL": mart.total_apps(), "METRIC": 0.0, "APP_IDS": lost[: p["limit"]],
             "RESULT": "FAIL" if lost else "PASS", "CONFIDENCE": "HIGH"}]

DEFAULTS = {"limit": 5}
CHECK = {"id": "qa_new_in_app", "label": "QA new check written in app", "params": DEFAULTS, "entrypoint": run}
'''


def test_script_kinds_publish_contract_template_example(api_a):
    kinds = {k["kind"]: k for k in api_a.get("/api/script-kinds").json()}
    assert set(KINDS) <= set(kinds)
    for k in KINDS:
        assert kinds[k]["entrypoint"] and kinds[k]["template"] and kinds[k]["example"] and kinds[k]["output_columns"]
        compile(kinds[k]["template"], k, "exec")
        compile(kinds[k]["example"], k, "exec")


def test_syntax_error_rejected_before_run(api_a):
    body = assert_envelope(api_a.script("check", "def run(:\n"), 422)
    assert body["code"] == "CODE_SYNTAX_ERROR" or "syntax" in body["message"].lower()


@pytest.fixture()
def trusted(execution_mode):
    if execution_mode != "trusted-local":
        pytest.skip("positive user-code path needs trusted-local server (builtin-only refusal is tested elsewhere)")


def test_example_procedures_run_in_every_slot(api_a, examples_root, trusted):
    """FR-018/AC-13: replace all four procedures with workspace code (the published examples), no rebuild."""
    kinds = {k["kind"]: k for k in api_a.get("/api/script-kinds").json()}
    slots = {}
    for k in ("normalize", "compare", "segments", "aggregate"):
        r = api_a.script(k, kinds[k]["example"])
        assert r.status_code == 201, r.text
        slots[k] = {"script_id": r.json()["script_id"]}
    ds = api_a.dataset(examples_root, "files", "I32554354_other.json", "I32554354.json")
    cfg = api_a.config(ds["dataset_id"], slots=slots)
    final = api_a.wait(f"/api/runs/{api_a.start_run(cfg['config_id']).json()['run_id']}")
    assert final["status"] == "COMPLETED", final
    for k, ref in slots.items():
        snap = api_a.get(f"/api/runs/{final['run_id']}/code/{k}").json()
        assert snap["script_id"] == ref["script_id"] and snap["source"] == "workspace"


def test_uploaded_py_check_runs(api_a, completed_example_run, trusted):
    """FR-007: placed .py file channel (source=file) works next to workspace code."""
    files = {"file": ("qa_uploaded.py", NEW_CHECK.replace("qa_new_in_app", "qa_uploaded").encode(), "text/x-python")}
    r = api_a.http.post("/api/scripts/upload", data={"kind": "check", "name": "qa uploaded"}, files=files)
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "file"
    cr = api_a.post(f"/api/runs/{completed_example_run['final']['run_id']}/check-runs",
                    {"checks": [{"script_id": r.json()["script_id"]}]})
    final = api_a.wait(f"/api/check-runs/{cr.json()['check_run_id']}")
    assert [e["execution_status"] for e in final["executions"]] == ["SUCCEEDED"]


def test_new_check_joins_original_five_in_new_common_report(api_a, completed_example_run, trusted):
    """FR-023/FR-026: original five + new check written in the app -> one new report; old report untouched."""
    run = completed_example_run["final"]
    initial_doc = api_a.get(f"/api/reports/{run['initial_report_id']}/checks").json()
    new = api_a.script("check", NEW_CHECK, params={"limit": 2})
    assert new.status_code == 201, new.text
    selected = [{"script_id": s["script_id"]} for s in api_a.builtin_checks()] + \
               [{"script_id": new.json()["script_id"], "params": {"limit": 1}}]
    cr = api_a.post(f"/api/runs/{run['run_id']}/check-runs", {"checks": selected})
    assert cr.status_code == 202, cr.text
    final = api_a.wait(f"/api/check-runs/{cr.json()['check_run_id']}")
    assert len(final["executions"]) == 6 and {e["execution_status"] for e in final["executions"]} == {"SUCCEEDED"}
    doc = api_a.get(f"/api/reports/{final['report_id']}/checks").json()
    labels = {r["LABEL"] for r in doc["checks"]}
    assert "QA new check written in app" in labels
    assert {r["LABEL"] for r in initial_doc["checks"]} <= labels
    mine = [r for r in doc["checks"] if r["LABEL"] == "QA new check written in app"][0]
    assert len(mine["APP_IDS"]) <= 1  # params from the check-run applied
    assert api_a.get(f"/api/reports/{run['initial_report_id']}/checks").json() == initial_doc


def test_exclusions_visible_and_editable_with_builtin_normalize(api_a):
    normalize = [s for s in api_a.get("/api/scripts", params={"kind": "normalize"}).json() if s["source"] == "builtin"]
    assert len(normalize) == 1, normalize
    kinds = {k["kind"]: k for k in api_a.get("/api/script-kinds").json()}
    exposed = str(normalize[0]["params"]) + str(kinds["normalize"])
    known_defect(normalize[0]["params"] == {"config": "real"} and "excluded" not in exposed,
                 "API-DISC-04: built-in normalize exposes only params.config in {real, teaching}; the exclusion "
                 "list (FR-019) is neither visible nor editable without custom code")
    assert "excluded" in exposed
