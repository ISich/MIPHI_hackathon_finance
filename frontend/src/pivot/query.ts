import type { PivotFilter } from "../api/types";

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
  return { rows: rows.length ? rows : ["DIFF_FLAG"], cols: list("cols"), filters };
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
