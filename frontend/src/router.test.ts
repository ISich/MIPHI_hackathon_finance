import { describe, expect, it } from "vitest";
import { deepLinkToHash, href, parseHash } from "./router";
import { parsePivotQuery, pivotQuery } from "./pivot/query";

describe("router", () => {
  it("parses hash path and query", () => {
    const r = parseHash("#/runs/run%201/checks?report=rep1");
    expect(r.parts).toEqual(["runs", "run 1", "checks"]);
    expect(r.query.get("report")).toBe("rep1");
  });
  it("defaults to the runs list", () => {
    expect(parseHash("").path).toBe("/runs");
  });
  it("encodes path parts", () => {
    expect(href("runs", "a/b")).toBe("#/runs/a%2Fb");
  });
  it("maps the HTML report deep link to the pivot of that Run with report context", () => {
    expect(deepLinkToHash("/runs/run_1/reports/rep_9")).toBe("#/runs/run_1/pivot?report=rep_9");
    expect(deepLinkToHash("/")).toBeNull();
    expect(deepLinkToHash("/runs/run_1")).toBeNull();
  });
});

describe("pivot layout in URL", () => {
  it("round-trips rows, cols and filters (incl. empty-string values)", () => {
    const s = { rows: ["PATH", "SOURCE"], cols: ["DIFF_FLAG"], filters: [{ dim: "PREFIX", op: "in" as const, values: ["decision", ""] }] };
    const back = parsePivotQuery(new URLSearchParams(pivotQuery(s)));
    expect(back).toEqual(s);
  });
  it("defaults rows when none given", () => {
    expect(parsePivotQuery(new URLSearchParams("")).rows.length).toBeGreaterThan(0);
  });
});
