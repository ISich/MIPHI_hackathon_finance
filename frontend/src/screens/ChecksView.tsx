import { rowsByExecution } from "../api/client";
import { api } from "../api/instance";
import type { CheckExecution, CheckRow, ReportChecks, Run } from "../api/types";
import { ExecBadge, ResultBadge } from "../components/Badges";
import { Async, Empty } from "../components/StateView";
import { useApi } from "../hooks/useApi";
import { href, navigate } from "../router";

/**
 * Checks of ONE explicit report: ?report=<id> or the Run's initial_report_id
 * (never an implicit "latest").
 */
export function ChecksView({ run, reportId }: { run: Run; reportId: string | null }) {
  const selected = reportId ?? run.initial_report_id ?? null;
  const reports = useApi(`reports:${run.run_id}`, () => api.reports(run.run_id));
  const checks = useApi(selected ? `report-checks:${selected}` : null, () => api.reportChecks(selected!));
  return (
    <div>
      <div className="row-between">
        <Async value={reports} what="Загрузка отчётов">
          {(list) => (
            <label>
              Отчёт{" "}
              <select
                aria-label="Отчёт"
                value={selected ?? ""}
                onChange={(e) => navigate(`${href("runs", run.run_id, "checks")}?report=${encodeURIComponent(e.target.value)}`)}
              >
                {list.items.map((r) => (
                  <option key={r.report_id} value={r.report_id}>
                    {r.report_id} {r.report_id === list.initial_report_id ? "(исходный)" : "(повтор проверок)"} — {r.status}
                    {r.completeness ? `, ${r.completeness}` : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
        </Async>
        {selected ? (
          <a className="button" href={api.reportHtmlUrl(selected)} target="_blank" rel="noopener noreferrer" download={`${selected}.html`}>
            Скачать HTML-отчёт
          </a>
        ) : null}
      </div>
      {!selected ? (
        <Empty>У Run нет initial_report_id — отчёт по проверкам не опубликован.</Empty>
      ) : (
        <Async value={checks} what="Загрузка результатов проверок">
          {(d) => (d.report_id !== selected ? null : <ReportBody doc={d} runId={run.run_id} />)}
        </Async>
      )}
    </div>
  );
}

function ReportBody({ doc, runId }: { doc: ReportChecks; runId: string }) {
  const groups = rowsByExecution(doc);
  const failedExec = doc.executions.filter((e) => e.execution_status !== "SUCCEEDED").length;
  return (
    <div>
      <p className="check-summary" data-testid="check-summary">
        Отчёт <code>{doc.report_id}</code>, полнота: <strong>{doc.completeness}</strong>. Проверок: {doc.executions.length}; строк FAIL:{" "}
        {doc.checks.filter((r) => r.RESULT === "FAIL").length}, PASS: {doc.checks.filter((r) => r.RESULT === "PASS").length}
        {failedExec ? (
          <>
            ; <strong className="err">ошибок исполнения: {failedExec}</strong> (отчёт по проверкам неполный)
          </>
        ) : null}
      </p>
      {doc.completeness === "NO_CHECKS_SELECTED" ? <Empty>Проверки не выбирались (технический Run).</Empty> : null}
      {groups ? (
        groups.map(({ ex, rows }) => <ExecutionCard key={ex.execution_id} ex={ex} rows={rows} doc={doc} runId={runId} />)
      ) : (
        <>
          <div className="state state-notready">Число строк не сходится с rows_count исполнений — строки показаны без привязки к проверке.</div>
          {doc.executions.map((ex) => (
            <ExecutionCard key={ex.execution_id} ex={ex} rows={null} doc={doc} runId={runId} />
          ))}
          <RowsTable rows={doc.checks} runId={runId} label="Все строки отчёта" />
        </>
      )}
    </div>
  );
}

function ExecutionCard({ ex, rows, doc, runId }: { ex: CheckExecution; rows: CheckRow[] | null; doc: ReportChecks; runId: string }) {
  const ok = ex.execution_status === "SUCCEEDED";
  const diags = doc.diagnostics.filter((d) => d.check === (ex.check_id ?? ex.slot) || d.check === ex.slot);
  return (
    <article className={`card ${ok ? "" : "card-error"}`} data-testid="check-execution" data-exec-status={ex.execution_status}>
      <header className="row-between">
        <h3>
          {ex.label ?? ex.check_id ?? ex.slot} <span className="muted">({ex.check_id ?? "id неизвестен"}, {ex.slot})</span>
        </h3>
        <ExecBadge status={ex.execution_status} />
      </header>
      <div className="muted">
        Параметры: <code>{JSON.stringify(ex.params ?? {})}</code>
        {ex.duration_seconds !== null ? ` · ${ex.duration_seconds} с` : ""}
      </div>
      {!ok ? (
        <div className="state state-error">
          Проверка не исполнилась — это не FAIL, бизнес-результата нет.
          {diags.map((d, i) => (
            <div key={i}>
              <code>{String(d.error_type ?? "")}</code> {String(d.message ?? "")}
            </div>
          ))}
        </div>
      ) : rows === null ? null : rows.length === 0 ? (
        <p className="muted">Исполнена успешно, 0 строк результата (это не PASS).</p>
      ) : (
        <RowsTable rows={rows} runId={runId} label={`Результаты ${ex.check_id ?? ex.slot}`} />
      )}
    </article>
  );
}

function RowsTable({ rows, runId, label }: { rows: CheckRow[]; runId: string; label: string }) {
  return (
    <div className="table-wrap">
      <table className="table" aria-label={label}>
        <thead>
          <tr>
            <th>Результат</th>
            <th>SOURCE</th>
            <th>ARGUMENT</th>
            <th>CNT / TOTAL</th>
            <th>METRIC</th>
            <th>Примеры APP_ID</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={r.CONFIDENCE === "LOW" ? "low" : ""} data-result={r.RESULT} data-confidence={r.CONFIDENCE}>
              <td>
                <ResultBadge result={r.RESULT} low={r.CONFIDENCE === "LOW"} />
              </td>
              <td>{r.SOURCE}</td>
              <td>{r.ARGUMENT || <span className="muted">—</span>}</td>
              <td className="num">
                {r.CNT} / {r.TOTAL}
              </td>
              <td className="num">{r.METRIC}</td>
              <td>
                {r.APP_IDS.length ? (
                  <>
                    <span className="muted">
                      {r.APP_IDS.length} пример(ов) из {r.CNT}:{" "}
                    </span>
                    {r.APP_IDS.map((a) => (
                      <a key={a} href={href("runs", runId, "apps", a)} className="app-chip">
                        {a}
                      </a>
                    ))}
                  </>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
