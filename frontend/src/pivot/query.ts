import type { PivotFilter, PivotRequest } from "../api/types";

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
    if (k.startsWith("f.")) filters.push({ dim: k.slice(2), op: "in", values: v.split("|") });
  });
  const rows = list("rows");
  const cols = list("cols");
  return { rows: rows.length || cols.length ? rows : ["DIFF_FLAG"], cols, filters };
}

/** Only PivotQuery fields cross the API boundary; axes/report live in the URL. */
export function pivotRequest(s: PivotState, offset = 0): PivotRequest {
  return {
    dimensions: [...new Set([...s.rows, ...s.cols])],
    filters: Object.fromEntries(s.filters.map(f => [f.dim, f.op === "eq" ? f.values[0] : f.values])),
    limit: 100, offset,
  };
}

export function pivotQuery(s: PivotState): string {
  const q = new URLSearchParams();
  if (s.rows.length) q.set("rows", s.rows.join(","));
  if (s.cols.length) q.set("cols", s.cols.join(","));
  for (const f of s.filters) q.set(`f.${f.dim}`, f.values.join("|"));
  return q.toString();
}

export type Key = Array<string | number | null>;
export const keyStr = (k: Key) => JSON.stringify(k);
export const keyLabel = (k: Key) => (k.length ? k.map((v) => (v === "" ? "∅ (пусто)" : v === null ? "—" : String(v))).join(" · ") : "Все");
