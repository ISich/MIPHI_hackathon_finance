import { useState } from "react";
import { api } from "../api/instance";
import { Async } from "../components/StateView";
import { useApi } from "../hooks/useApi";
import { href } from "../router";

export const PAGE_SIZE = 50;

export function GroupApplications({ runId, group, back }: { runId: string; group: string; back: string }) {
  const [offset, setOffset] = useState(0);
  const page = useApi(`group:${runId}:${group}:${offset}`, () => api.groupApplications(runId, group, offset, PAGE_SIZE));
  const backHref = `${href("runs", runId, "pivot")}${back ? `?${back}` : ""}`;
  return (
    <section>
      <p>
        <a href={backHref}>← К сводной (фильтры сохранены)</a>
      </p>
      <h1>Заявки группы</h1>
      <Async value={page} what="Загрузка заявок">
        {(p) => (
          <div>
            <p data-testid="group-total">
              Всего различных заявок: <strong>{p.total ?? "не сообщено backend"}</strong>
              {p.items.length ? `; показаны ${offset + 1}–${offset + p.items.length}` : ""}
            </p>
            {p.items.length === 0 ? <p className="muted">На этой странице заявок нет.</p> : null}
            <ul className="app-list">
              {p.items.map((app) => (
                <li key={app}>
                  <a href={`${href("runs", runId, "apps", app)}?group=${encodeURIComponent(group)}&back=${encodeURIComponent(back)}`}>{app}</a>
                </li>
              ))}
            </ul>
            <div className="pager">
              <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                ← Назад
              </button>
              <button
                type="button"
                disabled={p.total === null ? p.items.length < PAGE_SIZE : offset + PAGE_SIZE >= p.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Далее →
              </button>
            </div>
          </div>
        )}
      </Async>
    </section>
  );
}

export const MAX_FACT_APPS = 10000;

/** Drill-down from a D4 base fact (fallback mode): POST /pivot-facts/applications. */
export function FactApplications({ runId, group, cnt }: { runId: string; group: string; cnt: number | null }) {
  let parsed: Record<string, unknown> | null = null;
  try {
    const v: unknown = JSON.parse(group);
    if (v && typeof v === "object" && !Array.isArray(v)) parsed = v as Record<string, unknown>;
  } catch {
    parsed = null;
  }
  const limit = Math.min(MAX_FACT_APPS, Math.max(1, cnt ?? 200));
  const page = useApi(parsed ? `fact-apps:${runId}:${group}:${limit}` : null, () => api.pivotFactApplications(runId, parsed!, limit));
  return (
    <section>
      <p>
        <a href={href("runs", runId, "pivot")}>← К базовым фактам</a>
      </p>
      <h1>Заявки факта</h1>
      {parsed ? (
        <dl className="kv">
          {Object.entries(parsed).map(([k, v]) => (
            <div key={k} className="kv-pair">
              <dt>{k}</dt>
              <dd>{v === "" ? "∅ (пусто)" : String(v)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <div className="state state-error">Некорректная ссылка на группу.</div>
      )}
      <Async value={page} what="Загрузка заявок">
        {(p) => (
          <div>
            <p data-testid="group-total">
              Получено заявок: <strong>{p.items.length}</strong>
              {cnt !== null ? `; CNT факта: ${cnt}` : ""}
              {p.total === null ? <span className="muted"> — полный distinct total backend не сообщает{p.total_note ? ` (${p.total_note})` : ""}</span> : `; всего: ${p.total}`}
            </p>
            <ul className="app-list">
              {p.items.map((app) => (
                <li key={app}>
                  <a href={href("runs", runId, "apps", app)}>{app}</a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Async>
    </section>
  );
}

export function ApplicationView({ runId, appId, group, back }: { runId: string; appId: string; group: string | null; back: string }) {
  const [onlyDiff, setOnlyDiff] = useState(true);
  const app = useApi(`app:${runId}:${appId}`, () => api.application(runId, appId));
  return (
    <section>
      <p>
        {group ? (
          <a href={`${href("runs", runId, "groups", group)}?back=${encodeURIComponent(back)}`}>← К заявкам группы</a>
        ) : (
          <a href={href("runs", runId, "pivot")}>← К сводной</a>
        )}
      </p>
      <h1>
        Заявка <code>{appId}</code>
      </h1>
      <Async value={app} what="Загрузка заявки">
        {(d) => {
          if (d.run_id !== runId) return null;
          const rows = onlyDiff ? d.comparison.filter((r) => Number(r.DIFF_FLAG) === 1) : d.comparison;
          return (
            <div>
              <h2>Сегменты</h2>
              <dl className="kv">
                {Object.entries(d.segment).map(([k, v]) => (
                  <div key={k} className="kv-pair">
                    <dt>{k}</dt>
                    <dd>{v === null || v === undefined ? "—" : String(v)}</dd>
                  </div>
                ))}
              </dl>
              <h2>Атрибуты BEFORE / AFTER</h2>
              <label>
                <input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} /> только различия
              </label>
              <div className="table-wrap">
                <table className="table" aria-label="Сравнение атрибутов">
                  <thead>
                    <tr>
                      <th>PATH</th>
                      <th>ARRAY_KEY</th>
                      <th>BEFORE</th>
                      <th>AFTER</th>
                      <th>Тип</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={`${r.PATH}|${r.ARRAY_KEY}`} className={`ct-${r.CHANGE_TYPE.toLowerCase()}`}>
                        <td>{r.PATH}</td>
                        <td>{r.ARRAY_KEY}</td>
                        <td>{r.CHANGE_TYPE === "ATTRIBUTE_NEW" ? <span className="muted">(нет)</span> : r.VALUE_BEFORE}</td>
                        <td>{r.CHANGE_TYPE === "ATTRIBUTE_LOST" ? <span className="muted">(нет)</span> : r.VALUE_AFTER}</td>
                        <td>{r.CHANGE_TYPE}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {rows.length === 0 ? <p className="muted">Различий нет.</p> : null}
            </div>
          );
        }}
      </Async>
    </section>
  );
}
