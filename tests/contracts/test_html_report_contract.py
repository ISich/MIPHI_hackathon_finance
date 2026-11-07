"""D4 html_report @ pinned core vs FR-010 / AC-15 / PRD §9 export rules, on a real check report."""
from __future__ import annotations

import re

import pytest

from support.fixtures import pair, run_real_pipeline

pytestmark = pytest.mark.contract

URL = "http://127.0.0.1:18999/runs/run_abc/report"


@pytest.fixture(scope="module")
def report(tmp_path_factory, organizer_checks_dir):
    from decision_diff.check_runner import discover_checks, run_checks
    from decision_diff.mart import DuckDBMart

    def to_reject(doc):
        doc["decisionResult"]["decision"] = "REJECT"
    run = run_real_pipeline(tmp_path_factory.mktemp("html"), [pair("H1", to_reject), pair("H2")])
    broken = tmp_path_factory.mktemp("bad") / "check_broken.py"
    broken.write_text("def run(m, p):\n    raise ValueError('<script>x</script>')\n"
                      "CHECK = {'id': 'broken', 'label': 'b', 'params': {}, 'entrypoint': run}\n", encoding="utf-8")
    with DuckDBMart(run.db) as mart:
        outcome = run_checks(mart, [*discover_checks(organizer_checks_dir), broken])
        summary = {"total_apps": mart.total_apps(), "changed_apps": len(mart.app_ids(diff_flag=1)),
                   "decision_changed_apps": 1}
    return {"summary": summary, "checks": outcome.rows, "diagnostics": outcome.diagnostics}


def test_html_has_all_rows_errors_and_absolute_link(report):
    from decision_diff.html_report import render_html_report

    html = render_html_report(report, report_url=URL)
    assert html.count("<tr class=") == len(report["checks"])
    assert f'href="{URL}"' in html
    assert "ValueError" in html and "<script>x" not in html  # error shown, escaped
    assert re.search(r"FAIL<strong>\d+", html)


def test_html_rejects_non_http_link(report):
    from decision_diff.html_report import ReportDataError, render_html_report

    for bad in ("javascript:alert(1)", "/relative/path", "file:///etc/passwd"):
        with pytest.raises(ReportDataError):
            render_html_report(report, report_url=bad)


@pytest.mark.xfail(reason="DISC-10: HTML export has no Run ID / report_id / check params / completeness flag "
                          "(PRD §9: export contains Run ID, parameters/completeness; api.md: HTML built for a "
                          "concrete report_id). Renderer takes only summary/checks/diagnostics.")
def test_html_identifies_run_and_report(report):
    from decision_diff.html_report import render_html_report

    html = render_html_report({**report, "run_id": "run_abc", "report_id": "rep_1"}, report_url=URL)
    assert "run_abc" in html.replace(URL, "") and "rep_1" in html


@pytest.mark.xfail(reason="DISC-11: with execution errors present the HTML has no explicit 'checks incomplete' "
                          "marker; only a diagnostics list (PRD §10: заметная пометка «проверки выполнены не полностью»).")
def test_html_marks_incomplete_checks(report):
    from decision_diff.html_report import render_html_report

    html = render_html_report(report, report_url=URL).lower()
    assert "не полностью" in html or "incomplete" in html
