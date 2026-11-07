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
      {(d) => (
        <div>
          <div className="tiles" aria-label="Итоговые показатели">
            <Tile label="Заявок" value={d.total_apps} />
            <Tile label="Изменилось заявок" value={d.changed_apps} />
            <Tile label="Смена решения" value={d.decision_changed_apps} />
            <Tile label="Изменённых атрибутов" value={d.changed_attributes} />
            <Tile label="Approval rate до → после" value={`${pct(d.approval_rate_before)} → ${pct(d.approval_rate_after)}`} />
          </div>
          <h2>Типы изменений</h2>
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
          ) : null}
          {d.completeness ? (
            <details>
              <summary>Полнота / диагностика</summary>
              <pre className="details">{JSON.stringify({ completeness: d.completeness, diagnostics: d.diagnostics ?? [] }, null, 2)}</pre>
            </details>
          ) : null}
        </div>
      )}
    </Async>
  );
}

function Tile({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="tile">
      <div className="tile-value">{value}</div>
      <div className="tile-label">{label}</div>
    </div>
  );
}
