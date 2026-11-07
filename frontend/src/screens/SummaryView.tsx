import { api } from "../api/instance";
import type { Run } from "../api/types";
import { Async } from "../components/StateView";
import { useApi } from "../hooks/useApi";
import { href } from "../router";

const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

export function SummaryView({ run }: { run: Run }) {
  const s = useApi(`summary:${run.run_id}`, () => api.summary(run.run_id));
  return (
    <Async value={s} what="Загрузка сводки">
      {(d) =>
        d.run_id !== run.run_id ? null : (
          <div>
            <p className="muted">
              Числа получены backend из расчёта этого Run (dataset revision <code>{d.dataset_revision_id ?? run.dataset_revision_id}</code>).
            </p>
            <div className="tiles" aria-label="Итоговые показатели">
              <Tile label="Заявок" value={d.total_apps} testId="tile-total" />
              <Tile label="Изменилось заявок" value={d.changed_apps} testId="tile-changed" />
              <Tile label="Смена решения" value={d.decision_changed_apps} testId="tile-decision" />
              <Tile label="Изменённых атрибутов" value={d.changed_attributes} />
              <Tile label="Approval rate до → после" value={`${pct(d.approval_rate_before)} → ${pct(d.approval_rate_after)}`} />
            </div>
            <h2>Типы изменений</h2>
            <p className="muted">Число строк сравнения (атрибутов) по типу, не число заявок.</p>
            <table className="table" aria-label="Типы изменений">
              <tbody>
                {Object.entries(d.change_types).map(([k, v]) => (
                  <tr key={k}>
                    <th>{k}</th>
                    <td className="num">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {d.top_paths?.length ? (
              <>
                <h2>Top PATH</h2>
                <table className="table" aria-label="Top PATH">
                  <tbody>
                    {d.top_paths.map((t) => (
                      <tr key={t.path}>
                        <td>
                          <a href={`${href("runs", run.run_id, "pivot")}?rows=PATH&f.PATH=${encodeURIComponent(t.path)}`}>{t.path}</a>
                        </td>
                        <td className="num">{t.changed_apps}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            ) : (
              <p className="muted">Top PATH backend пока не отдаёт.</p>
            )}
            <h2>Полнота проверок</h2>
            <p data-testid="completeness">
              {run.checks_completeness ?? "—"}
              {run.checks_completeness === "INCOMPLETE" ? " — часть проверок не исполнилась, см. «Проверки»" : ""}
              {run.checks_completeness === "NO_CHECKS_SELECTED" ? " — технический Run без проверок, не доказательство приёмки checks" : ""}
            </p>
            {d.artifacts?.length ? (
              <>
                <h2>Артефакты</h2>
                <table className="table" aria-label="Артефакты">
                  <tbody>
                    {d.artifacts.map((a) => (
                      <tr key={a.artifact_id}>
                        <td>{a.kind}</td>
                        <td className="num">{a.rows ?? "—"} строк</td>
                        <td className="num">{a.bytes} байт</td>
                        <td>
                          <a href={a.download}>скачать</a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            ) : null}
          </div>
        )
      }
    </Async>
  );
}

function Tile({ label, value, testId }: { label: string; value: number | string; testId?: string }) {
  return (
    <div className="tile" data-testid={testId}>
      <div className="tile-value">{value}</div>
      <div className="tile-label">{label}</div>
    </div>
  );
}
