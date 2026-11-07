import { api } from "../api/instance";
import type { CheckExecution, Run } from "../api/types";
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
              Отчёт
              <select
                aria-label="Отчёт"
                value={selected ?? ""}
                onChange={(e) => navigate(`${href("runs", run.run_id, "checks")}?report=${encodeURIComponent(e.target.value)}`)}
              >
                {list.map((r) => (
                  <option key={r.report_id} value={r.report_id}>
                    {r.report_id} {r.report_id === run.initial_report_id ? "(исходный)" : "(повтор checks)"} — {r.status}
                  </option>
                ))}
              </select>
            </label>
          )}
        </Async>
        {selected ? (
          <a className="button" href={api.reportHtmlUrl(selected)} target="_blank" rel="noopener noreferrer">
            Скачать HTML-отчёт
          </a>
        ) : null}
      </div>
      {!selected ? (
        <Empty>У Run нет initial_report_id — отчёт по проверкам не опубликован.</Empty>
      ) : (
        <Async value={checks} what="Загрузка результатов проверок" isEmpty={(d) => d.executions.length === 0} empty="В отчёте нет выбранных проверок.">
          {(d) =>
            d.report_id !== selected ? null : (
              <div>
                <CheckSummary executions={d.executions} />
                {d.executions.map((ex) => (
                  <ExecutionCard key={ex.execution_id} ex={ex} runId={run.run_id} />
                ))}
              </div>
            )
          }
        </Async>
      )}
    </div>
  );
}

function CheckSummary({ executions }: { executions: CheckExecution[] }) {
  const rows = executions.flatMap((e) => e.rows);
  const errors = executions.filter((e) => e.execution_status !== "SUCCESS").length;
  return (
    <p className="check-summary" data-testid="check-summary">
      Проверок: {executions.length}; строк FAIL: {rows.filter((r) => r.RESULT === "FAIL").length}, PASS: {rows.filter((r) => r.RESULT === "PASS").length}
      {errors ? (
        <>
          ; <strong className="err">ошибок исполнения: {errors}</strong> (отчёт по проверкам неполный)
        </>
      ) : null}
    </p>
  );
}

function ExecutionCard({ ex, runId }: { ex: CheckExecution; runId: string }) {
  const ok = ex.execution_status === "SUCCESS";
  return (
    <article className={`card ${ok ? "" : "card-error"}`} data-testid="check-execution" data-exec-status={ex.execution_status}>
      <header className="row-between">
        <h3>{ex.label ?? ex.check_id ?? ex.script_id}</h3>
        <ExecBadge status={ex.execution_status} />
      </header>
      {Object.keys(ex.params ?? {}).length ? (
        <div className="muted">
          Параметры: <code>{JSON.stringify(ex.params)}</code>
        </div>
      ) : null}
      {!ok ? (
        <div className="state state-error">
          Проверка не исполнилась — это не FAIL, результата нет.
          {ex.diagnostics ? (
            <div>
              <code>{String(ex.diagnostics.error_type ?? "")}</code> {String(ex.diagnostics.message ?? "")}
            </div>
          ) : null}
        </div>
      ) : ex.rows.length === 0 ? (
        <p className="muted">Исполнена успешно, 0 строк результата.</p>
      ) : (
        <div className="table-wrap">
          <table className="table" aria-label={`Результаты ${ex.check_id ?? ""}`}>
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
              {ex.rows.map((r, i) => (
                <tr key={i} className={r.CONFIDENCE === "LOW" ? "low" : ""}>
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
      )}
    </article>
  );
}
