import { useMemo, useState } from "react";
import { api } from "../api/instance";
import { PIVOT_DIMENSIONS, type PivotFilter, type PivotResponse, type Run } from "../api/types";
import { Async } from "../components/StateView";
import { useApi } from "../hooks/useApi";
import { href, navigate } from "../router";

export interface PivotState {
  rows: string[];
  cols: string[];
  filters: PivotFilter[];
}

/** Layout lives in the URL query, so drill-down "back" restores exactly the same layout and filters. */
export function parsePivotQuery(q: URLSearchParams): PivotState {
  const list = (k: string) => (q.get(k) ?? "").split(",").filter(Boolean);
  const filters: PivotFilter[] = [];
  q.forEach((v, k) => {
    if (k.startsWith("f.") && v !== "") filters.push({ dim: k.slice(2), op: "in", values: v.split("|") });
  });
  const rows = list("rows");
  return { rows: rows.length ? rows : ["CHANGE_TYPE"], cols: list("cols"), filters };
}

export function pivotQuery(s: PivotState): string {
  const q = new URLSearchParams();
  if (s.rows.length) q.set("rows", s.rows.join(","));
  if (s.cols.length) q.set("cols", s.cols.join(","));
  for (const f of s.filters) q.set(`f.${f.dim}`, f.values.join("|"));
  return q.toString();
}

const keyStr = (k: Array<string | number | null>) => JSON.stringify(k);
const label = (k: Array<string | number | null>) => (k.length ? k.map((v) => (v === "" ? "∅ (пусто)" : v === null ? "—" : String(v))).join(" · ") : "Все");

export function PivotView({ run, query }: { run: Run; query: URLSearchParams }) {
  const state = parsePivotQuery(query);
  const qs = pivotQuery(state);
  const pivot = useApi(`pivot:${run.run_id}:${qs}`, () =>
    api.pivot(run.run_id, { rows: state.rows, cols: state.cols, filters: state.filters, report_id: run.initial_report_id ?? null }),
  );
  const go = (s: PivotState) => navigate(`${href("runs", run.run_id, "pivot")}?${pivotQuery(s)}`);

  return (
    <div>
      <PivotControls state={state} onChange={go} />
      <Async value={pivot} what="Расчёт сводной на сервере" isEmpty={(d) => d.cells.length === 0 && d.grand_total.count === 0} empty="Нет данных для выбранных фильтров.">
        {(d) =>
          d.run_id !== run.run_id ? null : <PivotTable data={d} runId={run.run_id} backQuery={qs} />
        }
      </Async>
    </div>
  );
}

function PivotControls({ state, onChange }: { state: PivotState; onChange: (s: PivotState) => void }) {
  const [fDim, setFDim] = useState<string>(PIVOT_DIMENSIONS[0]);
  const [fVal, setFVal] = useState("");
  const used = new Set([...state.rows, ...state.cols]);
  const DimList = ({ which }: { which: "rows" | "cols" }) => (
    <div className="dimlist" aria-label={which === "rows" ? "Строки" : "Колонки"}>
      <strong>{which === "rows" ? "Строки:" : "Колонки:"}</strong>
      {state[which].map((d) => (
        <span key={d} className="chip">
          {d}
          <button type="button" aria-label={`Убрать ${d}`} onClick={() => onChange({ ...state, [which]: state[which].filter((x) => x !== d) })}>
            ×
          </button>
        </span>
      ))}
      <select
        aria-label={which === "rows" ? "Добавить строку" : "Добавить колонку"}
        value=""
        onChange={(e) => e.target.value && onChange({ ...state, [which]: [...state[which], e.target.value] })}
      >
        <option value="">+ измерение</option>
        {PIVOT_DIMENSIONS.filter((d) => !used.has(d)).map((d) => (
          <option key={d} value={d}>
            {d}
          </option>
        ))}
      </select>
    </div>
  );
  return (
    <div className="pivot-controls">
      <DimList which="rows" />
      <DimList which="cols" />
      <button type="button" onClick={() => onChange({ ...state, rows: state.cols, cols: state.rows })} disabled={!state.cols.length}>
        ⇄ Поменять строки и колонки
      </button>
      <div className="dimlist" aria-label="Фильтры">
        <strong>Фильтры:</strong>
        {state.filters.map((f) => (
          <span key={f.dim} className="chip">
            {f.dim} ∈ {f.values.map((v) => (v === "" ? "∅" : v)).join(" | ")}
            <button type="button" aria-label={`Убрать фильтр ${f.dim}`} onClick={() => onChange({ ...state, filters: state.filters.filter((x) => x.dim !== f.dim) })}>
              ×
            </button>
          </span>
        ))}
        <select aria-label="Измерение фильтра" value={fDim} onChange={(e) => setFDim(e.target.value)}>
          {PIVOT_DIMENSIONS.map((d) => (
            <option key={d}>{d}</option>
          ))}
        </select>
        <input aria-label="Значение фильтра" placeholder="значение (| — несколько)" value={fVal} onChange={(e) => setFVal(e.target.value)} />
        <button
          type="button"
          onClick={() => {
            onChange({ ...state, filters: [...state.filters.filter((x) => x.dim !== fDim), { dim: fDim, op: "in", values: fVal.split("|") }] });
            setFVal("");
          }}
        >
          Добавить фильтр
        </button>
      </div>
    </div>
  );
}

export function PivotTable({ data, runId, backQuery }: { data: PivotResponse; runId: string; backQuery: string }) {
  const { rowKeys, colKeys, cellMap } = useMemo(() => {
    const m = new Map<string, { count: number; group: string }>();
    for (const c of data.cells) m.set(keyStr(c.row) + "|" + keyStr(c.col), c);
    return {
      rowKeys: data.row_totals.map((t) => t.key),
      colKeys: data.col_totals.length ? data.col_totals.map((t) => t.key) : [[]],
      cellMap: m,
    };
  }, [data]);
  const drill = (group: string) => `${href("runs", runId, "groups", group)}?back=${encodeURIComponent(backQuery)}`;
  const Cell = ({ c }: { c?: { count: number; group: string } }) =>
    c && c.count > 0 ? (
      <a href={drill(c.group)} title="Открыть заявки группы">
        {c.count}
      </a>
    ) : (
      <span className="muted">0</span>
    );
  const hasCols = data.cols.length > 0;
  return (
    <div className="table-wrap">
      <p className="muted">
        Значения — число различных заявок (COUNT DISTINCT APP_ID), посчитано сервером. Итоги не являются суммой ячеек: одна заявка может попасть в несколько групп.
      </p>
      {data.truncated ? <p className="state state-notready">Результат усечён сервером.</p> : null}
      <table className="table pivot" aria-label="Сводная таблица">
        <thead>
          <tr>
            <th>{data.rows.join(" · ") || "—"}</th>
            {hasCols ? colKeys.map((k) => <th key={keyStr(k)}>{label(k)}</th>) : <th>Заявок</th>}
            {hasCols ? <th>Итого</th> : null}
          </tr>
        </thead>
        <tbody>
          {rowKeys.map((rk) => {
            const rt = data.row_totals.find((t) => keyStr(t.key) === keyStr(rk));
            return (
              <tr key={keyStr(rk)}>
                <th>{label(rk)}</th>
                {hasCols ? colKeys.map((ck) => <td key={keyStr(ck)} className="num"><Cell c={cellMap.get(keyStr(rk) + "|" + keyStr(ck))} /></td>) : null}
                <td className="num total">
                  <Cell c={rt} />
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <th>Итого</th>
            {hasCols ? data.col_totals.map((t) => <td key={keyStr(t.key)} className="num total"><Cell c={t} /></td>) : null}
            <td className="num total" data-testid="grand-total">
              <Cell c={data.grand_total} />
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
