from pathlib import Path

import pytest

from decision_diff.html_report import ReportDataError, render_html_report, write_html_report


@pytest.fixture
def report():
    return {
        'summary': {'total_apps': 5, 'changed_apps': 2, 'decision_changed_apps': 1},
        'checks': [
            {'LABEL': '<script>alert(1)</script>', 'SOURCE': 'AFTER', 'ARGUMENT': 'foo & bar',
             'CNT': 2, 'TOTAL': 5, 'METRIC': 0.4, 'RESULT': 'FAIL',
             'CONFIDENCE': 'LOW', 'APP_IDS': ['A 1', 'X&Y']},
            {'LABEL': 'ok', 'SOURCE': 'AFTER', 'ARGUMENT': '-', 'CNT': 0,
             'TOTAL': 5, 'METRIC': 0.0, 'RESULT': 'PASS',
             'CONFIDENCE': 'HIGH', 'APP_IDS': []},
        ],
        'diagnostics': [],
    }


def test_html_escapes_untrusted_fields(report):
    html = render_html_report(report, report_url='https://example.org/runs/1/report')
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert '<script>alert(1)</script>' not in html
    assert 'foo &amp; bar' in html
    assert 'app_id=A%201' in html
    assert 'app_id=X%26Y' in html
    assert 'class="low"' in html
    assert 'Открыть интерактивный сводный отчёт' in html


def test_html_rejects_javascript_url(report):
    with pytest.raises(ReportDataError):
        render_html_report(report, report_url='javascript:alert(1)')


def test_html_rejects_invalid_report(report):
    bad = dict(report)
    bad['checks'] = [{'RESULT': 'UNKNOWN', 'CONFIDENCE': 'HIGH'}]
    with pytest.raises(ReportDataError):
        render_html_report(bad, report_url='https://example.org/runs/1/report')


def test_html_writes_utf8(tmp_path: Path, report):
    out = write_html_report(report, tmp_path / 'results' / 'report.html', report_url='https://example.org/runs/1/report')
    assert out.is_file()
    assert 'Проверка' in out.read_text(encoding='utf-8')
