"""Snapshot immutability (FR-027, AC-16/18) and check-only report identity (FR-026, api.md Report identity)."""
from __future__ import annotations

import hashlib

import pytest

from support.http_api import known_defect


CHECK_V1 = '''
def run(mart, params=None):
    return [{"LABEL": "qa v1", "SOURCE": "AFTER", "ARGUMENT": "v1", "CNT": 0, "TOTAL": mart.total_apps(),
             "METRIC": 0.0, "APP_IDS": [], "RESULT": "PASS", "CONFIDENCE": "HIGH"}]
CHECK = {"id": "qa_snapshot", "label": "qa snapshot", "params": {}, "entrypoint": run}
'''
CHECK_V2 = CHECK_V1.replace("qa v1", "qa v2").replace('"v1"', '"v2"')


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_config_and_code_snapshot_survive_script_edit(api_a, examples_root, execution_mode):
    if execution_mode != "trusted-local":  # CR2 #7: guard BEFORE any custom configuration is created
        pytest.skip("snapshot of custom code needs trusted-local; builtin-only refusal: test_execution_policy.py")
    script = api_a.script("check", CHECK_V1)
    assert script.status_code == 201, script.text
    sid = script.json()["script_id"]
    ds = api_a.dataset(examples_root, "files", "I32554354_other.json", "I32554354.json")
    cfg = api_a.config(ds["dataset_id"], checks=[{"script_id": sid}])
    accepted = api_a.start_run(cfg["config_id"])
    assert accepted.status_code == 202, accepted.text
    run_id = accepted.json()["run_id"]
    assert api_a.put(f"/api/scripts/{sid}", {"code": CHECK_V2}).status_code == 200  # edit right after accept
    final = api_a.wait(f"/api/runs/{run_id}")
    assert final["status"] == "COMPLETED", (final["status"], final["stage"], final["error"])
    snap = api_a.get(f"/api/runs/{run_id}/code/check-01").json()
    assert snap["code_sha256"] == _sha(CHECK_V1) and "qa v1" in snap["code"]
    rows = api_a.get(f"/api/runs/{run_id}/checks").json()["checks"]
    assert [r["ARGUMENT"] for r in rows if r["LABEL"].startswith("qa")] == ["v1"]
    assert api_a.get(f"/api/configurations/{cfg['config_id']}").json() == cfg
    # the NEXT run uses the new snapshot
    run2 = api_a.start_run(cfg["config_id"]).json()["run_id"]
    api_a.wait(f"/api/runs/{run2}")
    assert api_a.get(f"/api/runs/{run2}/code/check-01").json()["code_sha256"] == _sha(CHECK_V2)


def test_initial_report_is_stable_and_check_only_creates_new_identity(api_a, completed_example_run):
    run = completed_example_run["final"]
    run_id, initial = run["run_id"], run["initial_report_id"]
    before_doc = api_a.get(f"/api/runs/{run_id}/checks").json()
    before_html = api_a.get(f"/api/reports/{initial}/checks.html").text
    before_summary = api_a.get(f"/api/runs/{run_id}/summary").json()
    assert before_doc["report_id"] == initial

    builtin = [{"script_id": s["script_id"]} for s in api_a.builtin_checks()]
    assert len(builtin) == 5
    r = api_a.post(f"/api/runs/{run_id}/check-runs", {"checks": builtin})
    assert r.status_code == 202, r.text
    cr = r.json()
    assert cr["report_id"] != initial and cr["check_run_id"] != run["initial_check_run_id"]
    assert cr["dataset_revision_id"] == run["dataset_revision_id"] and cr["initial"] is False
    final_cr = api_a.wait(f"/api/check-runs/{cr['check_run_id']}")
    assert final_cr["status"] == "COMPLETED", final_cr

    assert api_a.get(f"/api/runs/{run_id}/checks").json() == before_doc  # alias never moves to latest
    assert api_a.get(f"/api/reports/{initial}/checks.html").text == before_html
    assert api_a.get(f"/api/runs/{run_id}/summary").json() == before_summary
    new_doc = api_a.get(f"/api/reports/{cr['report_id']}/checks").json()
    assert new_doc["report_id"] == cr["report_id"] and new_doc["run_id"] == run_id
    reports = api_a.get(f"/api/runs/{run_id}/reports").json()
    assert reports["initial_report_id"] == initial
    assert {initial, cr["report_id"]} <= {x["report_id"] for x in reports["items"]}
    rep = api_a.get(f"/api/reports/{cr['report_id']}").json()
    assert rep["status"] == "PUBLISHED" and rep["check_run_id"] == cr["check_run_id"]


class _HtmlProbe:
    """Parse anchors (href + visible text) and visible text nodes; attribute values are not 'text'."""

    def __init__(self, html: str):
        from html.parser import HTMLParser

        probe = self
        self.anchors, self.text = [], []

        class P(HTMLParser):
            current = None

            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    self.current = {"href": dict(attrs).get("href", ""), "text": ""}

            def handle_endtag(self, tag):
                if tag == "a" and self.current is not None:
                    probe.anchors.append(self.current)
                    self.current = None

            def handle_data(self, data):
                probe.text.append(data)
                if self.current is not None:
                    self.current["text"] += data

        P().feed(html)
        self.visible = " ".join(self.text)


def test_report_html_links_to_this_run(api_a, completed_example_run):
    """FR-010 / api.md (CR5 #6): the interactive-report anchor's TARGET is an absolute URL whose path is exactly
    /runs/{run_id}/reports/{report_id} of this report; per-application links point to the same report page."""
    from urllib.parse import parse_qs, urlsplit

    run = completed_example_run["final"]
    r = api_a.get(f"/api/reports/{run['initial_report_id']}/checks.html")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    probe = _HtmlProbe(r.text)
    main = [a for a in probe.anchors if "интерактивный" in a["text"]]
    assert len(main) == 1, probe.anchors[:3]
    target = urlsplit(main[0]["href"])
    expected_path = f"/runs/{run['run_id']}/reports/{run['initial_report_id']}"
    assert target.scheme in ("http", "https") and target.netloc, main[0]
    assert target.path.endswith(expected_path) and not target.query, main[0]
    app_links = [urlsplit(a["href"]) for a in probe.anchors if "app_id=" in a["href"]]
    assert app_links, "report of the example run must link its APP_IDS"
    for link in app_links:
        assert (link.scheme, link.netloc, link.path) == (target.scheme, target.netloc, target.path), link
        assert parse_qs(link.query)["app_id"][0] in probe.visible


def test_report_html_names_report_id(api_a, completed_example_run):
    """PRD §9: the exported HTML itself (visible text, not only the link URL) identifies Run and report."""
    run = completed_example_run["final"]
    r = api_a.get(f"/api/reports/{run['initial_report_id']}/checks.html")
    assert r.status_code == 200, r.text[:300]
    probe = _HtmlProbe(r.text)
    assert "Автоматические проверки" in probe.visible
    known_defect(run["initial_report_id"] not in probe.visible and run["run_id"] not in probe.visible,
                 "DISC-10 (D4 renderer): HTML visible text names neither report_id nor Run ID; only link URLs do")
    assert run["initial_report_id"] in probe.visible and run["run_id"] in probe.visible
