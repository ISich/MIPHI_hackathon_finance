"""Render a portable organizer-check report from a completed run.

Pure presentation module: no DuckDB, FastAPI or template engine required.
Outputs standalone HTML and links to the application's pivot/report route.
All JSON-derived text is escaped before interpolation into HTML.
"""
from __future__ import annotations

from collections import Counter
from html import escape
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlsplit


class ReportDataError(ValueError):
    """The check report is malformed or the base URL is unsafe."""


def _safe_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ReportDataError('A nonempty report URL is required')
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.netloc:
        raise ReportDataError('Report URL must be an absolute HTTP(S) URL')
    return url.rstrip('/')


def _h(value: object) -> str:
    return escape('' if value is None else str(value), quote=True)


def _format_value(value: object) -> str:
    if isinstance(value, float):
        return f'{value:.4f}'
    return '' if value is None else str(value)


def render_html_report(report: Mapping[str, Any], *, report_url: str, title: str = 'Отчёт автоматических проверок') -> str:
    """Return a self-contained HTML document.

    `report_url` is the permanent web route for this run's pivot page, e.g.
    https://example.org/runs/abc/report. It is embedded as the navigation
    target from the downloaded HTML. Per-app links use `${report_url}?app_id=...`.
    The frontend can decide how to interpret app_id (provisional convention).
    """
    base_url = _safe_url(report_url)
    summary = report.get('summary')
    checks = report.get('checks')
    diagnostics = report.get('diagnostics', [])
    if not isinstance(summary, Mapping) or not isinstance(checks, list) or not isinstance(diagnostics, list):
        raise ReportDataError('Expected summary object, checks array, diagnostics array')
    for field in ('total_apps', 'changed_apps', 'decision_changed_apps'):
        if field not in summary:
            raise ReportDataError(f'Missing summary field: {field}')
    statuses = Counter(str(row.get('RESULT')) for row in checks if isinstance(row, Mapping))
    if statuses.keys() - {'PASS', 'FAIL'}:
        raise ReportDataError('Unexpected check result status')

    body_rows = []
    for row in checks:
        if not isinstance(row, Mapping):
            raise ReportDataError('Check row must be an object')
        status = str(row.get('RESULT'))
        confidence = str(row.get('CONFIDENCE', ''))
        if confidence not in ('LOW', 'HIGH'):
            raise ReportDataError('Unexpected confidence level')
        apps = row.get('APP_IDS', [])
        if not isinstance(apps, list):
            raise ReportDataError('APP_IDS must be a list')
        css = 'low' if confidence == 'LOW' else ('failed' if status == 'FAIL' else 'passed')
        app_links = ', '.join(
            f'<a href="{_h(base_url + "?app_id=" + quote(str(app_id), safe=""))}">{_h(app_id)}</a>'
            for app_id in apps
        ) or '—'
        cells = [
            row.get('LABEL'), row.get('SOURCE'), row.get('ARGUMENT'),
            row.get('CNT'), row.get('TOTAL'), _format_value(row.get('METRIC')),
            row.get('RESULT'), row.get('CONFIDENCE'),
        ]
        html_cells = ''.join(f'<td>{_h(item)}</td>' for item in cells)
        body_rows.append(f'<tr class="{css}">{html_cells}<td class="apps">{app_links}</td></tr>')

    diagnostic_rows = []
    for d in diagnostics:
        if not isinstance(d, Mapping):
            raise ReportDataError('Diagnostic row must be an object')
        diagnostic_rows.append('<li>' + _h(d.get('check', '?')) + ': ' + _h(d.get('error_type', 'Error')) + ' — ' + _h(d.get('message', '')) + '</li>')
    diag_html = '<ul>' + ''.join(diagnostic_rows) + '</ul>' if diagnostic_rows else '<p>Ошибок исполнения нет.</p>'

    return f'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_h(title)}</title>
<style>
  :root {{ color-scheme: light; font-family: system-ui, -apple-system, Segoe UI, Arial, sans-serif; }}
  body {{ max-width: 1500px; margin: 2rem auto; padding: 0 1rem; color: #1f2937; background: #fff; }}
  h1 {{ font-size: 1.65rem; }}
  .summary {{ display: flex; flex-wrap: wrap; gap: 1rem; margin: 1.5rem 0; }}
  .metric {{ min-width: 145px; padding: 1rem; border: 1px solid #e5e7eb; border-radius: 8px; }}
  .metric strong {{ display: block; font-size: 1.5rem; }}
  .tablewrap {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .88rem; }}
  th,td {{ border-bottom: 1px solid #e5e7eb; padding: .65rem .5rem; text-align: left; vertical-align: top; }}
  th {{ background: #f3f4f6; position: sticky; top: 0; }}
  tr.failed {{ background: #fff1f2; }}
  tr.passed {{ background: #f0fdf4; }}
  tr.low {{ background: #fff8eb; }}
  a {{ color: #175cd3; }}
  td.apps {{ min-width: 280px; max-width: 420px; word-break: break-word; }}
  .muted {{ color: #6b7280; }}
  @media print {{ th {{ position: static; }} tr {{ break-inside: avoid; }} }}
</style>
</head>
<body>
<h1>{_h(title)}</h1>
<p>Сводный анализ BEFORE (MASTER) и AFTER (BETA). Данные отчёта сохранены в этом HTML.</p>
<p><a href="{_h(base_url)}">Открыть интерактивный сводный отчёт в приложении</a></p>
<div class="summary">
<div class="metric">Всего заявок<strong>{_h(summary['total_apps'])}</strong></div>
<div class="metric">С различиями<strong>{_h(summary['changed_apps'])}</strong></div>
<div class="metric">Со сменой решения<strong>{_h(summary['decision_changed_apps'])}</strong></div>
<div class="metric">PASS<strong>{statuses['PASS']}</strong></div>
<div class="metric">FAIL<strong>{statuses['FAIL']}</strong></div>
</div>
<h2>Автоматические проверки</h2>
<p class="muted">FAIL означает сигнал проверки, а не ошибку выполнения. Малые выборки с CONFIDENCE=LOW выделены мягко.</p>
<div class="tablewrap"><table>
<thead><tr><th>Проверка</th><th>Срез</th><th>Аргумент</th><th>CNT</th><th>TOTAL</th><th>Метрика</th><th>Результат</th><th>Уверенность</th><th>Заявки</th></tr></thead>
<tbody>{''.join(body_rows)}</tbody></table></div>
<h2>Диагностика выполнения</h2>{diag_html}
<p class="muted">Ссылки на отдельные заявки требуют доступного веб-приложения. Список APP_IDS в проверках может быть ограничен настройками проверки.</p>
</body></html>'''


def write_html_report(report: Mapping[str, Any], path: str | Path, *, report_url: str, title: str = 'Отчёт автоматических проверок') -> Path:
    """Write HTML as UTF-8; return the resolved path."""
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_html_report(report, report_url=report_url, title=title), encoding='utf-8')
    return destination
