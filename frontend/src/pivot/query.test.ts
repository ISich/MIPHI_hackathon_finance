import { describe, expect, it } from "vitest";
import { parsePivotQuery, pivotQuery, pivotRequest } from "./query";

describe("PivotQuery adapter", () => {
  it("deduplicates axes, maps scalar/list filters and excludes UI fields", () => {
    expect(pivotRequest({ rows: ["PATH"], cols: ["PATH", "CHANGE_TYPE"], filters: [
      { dim: "DIFF_FLAG", op: "eq", values: [1] },
      { dim: "SOURCE", op: "in", values: ["BEFORE", "AFTER"] },
    ] }, 100)).toEqual({ dimensions: ["PATH", "CHANGE_TYPE"], filters: { DIFF_FLAG: 1, SOURCE: ["BEFORE", "AFTER"] }, limit: 100, offset: 100 });
  });
  it("keeps column-only layouts and empty-string filters across navigation", () => {
    const s = parsePivotQuery(new URLSearchParams("cols=SOURCE&f.PATH="));
    expect(s.rows).toEqual([]);
    expect(parsePivotQuery(new URLSearchParams(pivotQuery(s)))).toEqual(s);
    expect(pivotRequest(s).filters).toEqual({ PATH: [""] });
  });
});
