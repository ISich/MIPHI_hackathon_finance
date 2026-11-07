import { useState } from "react";
import { api } from "../api/instance";
import type { PivotFact, Run } from "../api/types";
import { Async } from "../components/StateView";
import { useApi } from "../hooks/useApi";
import { href } from "../router";

export const FACTS_PAGE = 200;
export const FACT_COLUMNS = ["PATH", "ARRAY_KEY", "SOURCE", "VALUE_ADJUSTED", "DIFF_FLAG"] as const;
const DRILL_DIMS = ["PREFIX", "CLASS", "SUFFIX", "ARRAY_KEY", "KEY", "PATH", "VALUE_ADJUSTED", "DIFF_FLAG", "SOURCE"];

/** The drill-down group of a base fact: exactly its D4 dimensions (incl. SOURCE). */
export function factGroup(f: PivotFact): Record<string, unknown> {
  const g: Record<string, unknown> = {};
  for (const d of DRILL_DIMS) if (d in f) g[d] = f[d];
  return g;
}

/**
 * Fallback while the server rollup is unavailable: pages of D4 base facts
 * (GET /pivot-facts). CNT is per fact and must not be summed — no totals here.
 */
export function BaseFactsView({ run }: { run: Run }) {
  const [offset, setOffset] = useState(0);
  const [onlyDiff, setOnlyDiff] = useState(true);
  const page = useApi(`facts:${run.run_id}:${offset}`, () => api.pivotFacts(run.run_id, offset, FACTS_PAGE));
  return (
    <Async value={page} what="Загрузка базовых фактов" isEmpty={(p) => p.items.length === 0} empty="Базовых фактов нет.">
      {(p) => {
        const items = onlyDiff ? p.items.filter((f) => Number(f.DIFF_FLAG) === 1) : p.items;
        return (
          <div>
            <p className="muted">
              Факты {p.offset + 1}–{p.offset + p.items.length}. CNT — число различных заявок в одном факте; суммировать CNT между строками нельзя, поэтому
              итогов в этом режиме нет.
            </p>
            <label>
              <input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} /> только факты с DIFF_FLAG=1 (на этой странице)
            </label>
            <div className="table-wrap">
              <table className="table" aria-label="Базовые факты">
                <thead>
                  <tr>
                    {FACT_COLUMNS.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                    <th>CNT</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((f, i) => (
                    <tr key={i}>
                      {FACT_COLUMNS.map((c) => (
                        <td key={c}>{f[c] === "" ? <span className="muted">∅</span> : String(f[c] ?? "—")}</td>
                      ))}
                      <td className="num">
                        <a href={`${href("runs", run.run_id, "fact-apps")}?g=${encodeURIComponent(JSON.stringify(factGroup(f)))}&cnt=${f.CNT}`} title="Заявки этого факта">
                          {f.CNT}
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pager">
              <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - FACTS_PAGE))}>
                ← Назад
              </button>
              <button type="button" disabled={p.next_offset === null} onClick={() => setOffset(p.next_offset ?? offset)}>
                Далее →
              </button>
            </div>
          </div>
        );
      }}
    </Async>
  );
}
