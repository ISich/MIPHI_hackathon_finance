import type { PivotFact } from "../api/types";

export const FACTS_PAGE = 200;
export const FACT_COLUMNS = ["PATH", "ARRAY_KEY", "SOURCE", "VALUE_ADJUSTED", "DIFF_FLAG"] as const;
const DRILL_DIMS = ["PREFIX", "CLASS", "SUFFIX", "ARRAY_KEY", "KEY", "PATH", "VALUE_ADJUSTED", "DIFF_FLAG", "SOURCE"];

/** The drill-down group of a base fact: exactly its D4 dimensions (incl. SOURCE). */
export function factGroup(f: PivotFact): Record<string, unknown> {
  const g: Record<string, unknown> = {};
  for (const d of DRILL_DIMS) if (d in f) g[d] = f[d];
  return g;
}
