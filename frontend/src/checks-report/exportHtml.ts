import type { ReportChecks } from "../api/types";

const escapeHtml = (value: unknown): string => String(value ?? "").replace(/[&<>"']/g, character => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[character]!);

/** Presentation only: export the selected report's stored rows and verdicts without recalculating them. */
export function renderReportHtml(report: ReportChecks, appOrigin: string, demo = false): string {
  if (!report?.report_id || !report.run_id || !Array.isArray(report.checks) || !Array.isArray(report.executions) || !Array.isArray(report.diagnostics)) {
    throw new Error("Не удалось сформировать HTML: документ отчёта неполный.");
  }
  const origin = new URL(appOrigin);
  if (!["http:", "https:"].includes(origin.protocol)) throw new Error("Для ссылок отчёта нужен адрес приложения HTTP или HTTPS.");
  const reportUrl = new URL(`/runs/${encodeURIComponent(report.run_id)}/reports/${encodeURIComponent(report.report_id)}`, origin.origin);
  const failedExecutions = report.executions.filter(execution => execution.execution_status !== "SUCCEEDED");
  const emptyExecutions = report.executions.filter(execution => execution.execution_status === "SUCCEEDED" && execution.rows_count === 0);
  const incomplete = report.completeness === "INCOMPLETE" || failedExecutions.length > 0 || report.diagnostics.length > 0;

  const rows = report.checks.map(row => {
    if (!["PASS", "FAIL"].includes(row.RESULT) || !Array.isArray(row.APP_IDS)) {
      throw new Error("Не удалось сформировать HTML: некорректная строка проверки.");
    }
    const source = row.SOURCE === "BEFORE" ? "BEFORE (MASTER)" : row.SOURCE === "AFTER" ? "AFTER (BETA)" : row.SOURCE;
    const appLinks = row.APP_IDS.map(appId => {
      const appUrl = new URL(reportUrl);
      appUrl.searchParams.set("app_id", appId);
      return `<a href="${escapeHtml(appUrl.href)}">${escapeHtml(appId)}</a>`;
    }).join(", ");
    const apps = appLinks ? `<span class="examples">Примеры: ${row.APP_IDS.length} из ${escapeHtml(row.CNT)}</span>${appLinks}` : "—";
    return `<tr${row.CONFIDENCE === "LOW" ? ' class="low" title="Низкая уверенность (LOW)"' : ""}>
<th scope="row">${escapeHtml(row.LABEL)}</th>
<td class="source">${escapeHtml(source)}</td>
<td class="argument">${escapeHtml(row.ARGUMENT || "—")}</td>
<td class="numbers">${escapeHtml(row.CNT)} / ${escapeHtml(row.TOTAL)}</td>
<td class="metric">${escapeHtml(row.METRIC ?? "—")}</td>
<td><span class="result ${row.RESULT.toLowerCase()}">${row.RESULT}</span></td>
<td class="apps">${apps}</td></tr>`;
  }).join("\n");

  const executionProblems = failedExecutions.map(execution =>
    `<li>${escapeHtml(execution.label ?? execution.check_id ?? execution.slot)}: <code>${escapeHtml(execution.execution_status)}</code></li>`,
  ).join("");
  const diagnostics = report.diagnostics.map(diagnostic =>
    `<li>${escapeHtml(diagnostic.check ?? "Проверка")}: ${escapeHtml(diagnostic.error_type ?? "Ошибка")} — ${escapeHtml(diagnostic.message)}</li>`,
  ).join("");
  const completeness = incomplete
    ? '<p class="notice" role="note">Проверки выполнены не полностью (INCOMPLETE). Ошибки исполнения перечислены ниже и не подменяются результатами PASS или FAIL.</p>'
    : report.completeness === "NO_CHECKS_SELECTED" ? '<p class="notice">Проверки не выбирались.</p>' : "";
  const noRows = report.checks.length ? "" : '<p class="muted">Строк результатов нет.</p>';
  const noResults = emptyExecutions.length
    ? `<p class="muted">Без строк результата: ${emptyExecutions.map(execution => escapeHtml(execution.label ?? execution.check_id ?? execution.slot)).join(", ")}. Успешное исполнение без строк не означает PASS.</p>`
    : "";

  return `<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Отчёт проверок — ${escapeHtml(report.report_id)}</title>
<style>
:root { color-scheme: light; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: #26322c; background: #f5f7f2; }
* { box-sizing: border-box; }
body { max-width: 1440px; margin: 32px auto; padding: 0 28px; line-height: 1.6; }
h1 { font-size: 26px; line-height: 1.3; margin: 0 0 10px; }
h2 { font-size: 18px; margin: 28px 0 12px; }
p { margin: 0 0 16px; }
.meta, .muted { color: #738075; font-size: 12px; overflow-wrap: anywhere; }
.intro { max-width: 1120px; margin: 24px 0; }
.notice { padding: 12px 16px; background: #fff7df; border: 1px solid #decf9b; border-radius: 6px; }
.demo { background: #fff0e5; border-color: #e6bb9c; }
.table-wrap { overflow-x: auto; margin: 24px 0; }
table { border-collapse: collapse; width: 100%; min-width: 960px; font-size: 13px; }
th, td { padding: 12px 10px; border-bottom: 1px solid #dbe1d8; text-align: left; vertical-align: top; }
thead th { color: #808c7d; font-size: 10px; letter-spacing: .08em; text-transform: uppercase; font-weight: 600; border-bottom-color: #a3ad9e; }
tbody th { min-width: 190px; font-weight: 600; }
.source, .argument, .numbers, .metric { font-family: ui-monospace, "SFMono-Regular", Consolas, monospace; font-size: 12px; }
.source, .argument, .numbers, .metric, .result { white-space: nowrap; }
.result { display: inline-block; padding: 0 8px; line-height: 1.5; border: 1px solid; border-radius: 4px; font-family: ui-monospace, monospace; }
.pass { color: #416a35; border-color: #7f9e70; background: #edf4e7; }
.fail { color: #a14e46; border-color: #d8aaa3; background: #f9e9e5; }
.low { color: #929a8c; }
.low .result { border-style: dashed; }
.apps { min-width: 140px; max-width: 260px; overflow-wrap: anywhere; }
.examples { display: block; color: #738075; font-size: 10px; margin-bottom: 4px; }
a { color: #477b3e; text-underline-offset: 3px; }
code { font-family: ui-monospace, "SFMono-Regular", Consolas, monospace; }
li { overflow-wrap: anywhere; }
@media (max-width: 600px) { body { margin-block: 20px; padding-inline: 16px; } h1 { font-size: 22px; } }
@media print { body { margin: 0; padding: 0; max-width: none; } .table-wrap { overflow: visible; } table { min-width: 0; font-size: 10px; } .source, .argument { white-space: normal; overflow-wrap: anywhere; } tr { break-inside: avoid; } }
</style>
</head>
<body>
<h1>Отчёт проверок</h1>
<p class="meta">Запуск: <code>${escapeHtml(report.run_id)}</code> · Отчёт: <code>${escapeHtml(report.report_id)}</code><br>Версия данных: <code>${escapeHtml(report.dataset_revision_id)}</code></p>
${demo ? '<p class="notice demo">Демонстрационный отчёт: тестовые данные, не результат реального расчёта.</p>' : ""}
<p class="intro"><strong>Отчёт — одна общая таблица результатов всех проверок.</strong> Каждая проверка возвращает свои строки со срезом, аргументом, числами, метрикой и результатом. Данные сохранены в этом файле.</p>
${completeness}
<div class="table-wrap"><table aria-label="Результаты всех проверок">
<thead><tr><th>Проверка</th><th>Срез</th><th>Аргумент</th><th>Числа</th><th>Метрика</th><th>Результат</th><th>Заявки</th></tr></thead>
<tbody>${rows}</tbody></table></div>
${noRows}${noResults}
${executionProblems || diagnostics ? `<h2>Диагностика исполнения</h2><ul>${executionProblems}${diagnostics}</ul>` : ""}
<p class="muted">Пунктиром отмечены строки с низкой уверенностью (LOW). Сохранённые примеры заявок могут охватывать только часть указанного количества.</p>
<p><a href="${escapeHtml(reportUrl.href)}">Открыть результаты в приложении</a></p>
<p class="muted">Таблица доступна без подключения к серверу. Для перехода к заявкам требуется доступ к приложению.</p>
</body>
</html>`;
}

export function downloadReportHtml(report: ReportChecks, appOrigin: string, demo = false): void {
  const html = renderReportHtml(report, appOrigin, demo);
  const url = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${report.report_id.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")}.html`;
  document.body.appendChild(link);
  try { link.click(); } finally {
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
