import { describe, expect, it } from "vitest";
import { ApiClient, ApiError, rowsByExecution, slotOfCodeRef } from "./client";
import type { CheckExecution, CheckRow, ReportChecks } from "./types";

function fakeFetch(status: number, body: unknown, headers: Record<string, string> = {}) {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const f = async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response(typeof body === "string" ? body : JSON.stringify(body), { status, headers });
  };
  return { f, calls };
}

describe("ApiClient errors", () => {
  it("parses the {code,message,details,request_id} envelope into ApiError", async () => {
    const { f } = fakeFetch(409, { code: "NOT_READY", message: "Run not completed", details: { status: "RUNNING" }, request_id: "r1" });
    const err = await new ApiClient(f).summary("run1").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("NOT_READY");
    expect(err.status).toBe(409);
    expect(err.requestId).toBe("r1");
    expect(err.details).toEqual({ status: "RUNNING" });
    expect(err.isNotReady).toBe(true);
  });

  it("classifies CUSTOM_EXECUTION_DISABLED separately from a generic 403", async () => {
    const { f } = fakeFetch(403, { code: "CUSTOM_EXECUTION_DISABLED", message: "disabled", details: {}, request_id: "x" });
    const err: ApiError = await new ApiClient(f).createRun({ configuration_id: "c" }, "k").catch((e) => e);
    expect(err.isExecutionDisabled).toBe(true);
    expect(err.isForbidden).toBe(false);
    const { f: f2 } = fakeFetch(403, { code: "FORBIDDEN", message: "no", details: {}, request_id: "x" });
    const err2: ApiError = await new ApiClient(f2).run("r").catch((e) => e);
    expect(err2.isForbidden).toBe(true);
    expect(err2.isExecutionDisabled).toBe(false);
  });

  it("marks 501 ANALYTICS_UNAVAILABLE as unavailable", async () => {
    const { f } = fakeFetch(501, { code: "ANALYTICS_UNAVAILABLE", message: "not implemented", details: {}, request_id: "x" });
    const err: ApiError = await new ApiClient(f).pivot("r", { rows: [], cols: [], filters: [] }).catch((e) => e);
    expect(err.isUnavailable).toBe(true);
  });

  it("reports a non-envelope error body with HTTP_<status>", async () => {
    const { f } = fakeFetch(502, "<html>Bad gateway</html>", { "x-request-id": "gw" });
    const err: ApiError = await new ApiClient(f).runs().catch((e) => e);
    expect(err.code).toBe("HTTP_502");
    expect(err.requestId).toBe("gw");
  });

  it("turns a failed fetch into NETWORK_ERROR", async () => {
    const err: ApiError = await new ApiClient(async () => {
      throw new TypeError("Failed to fetch");
    })
      .runs()
      .catch((e) => e);
    expect(err.code).toBe("NETWORK_ERROR");
  });
});

describe("ApiClient requests", () => {
  it("accepts list endpoints as bare arrays and as {items} pages", async () => {
    expect(await new ApiClient(fakeFetch(200, [{ dataset_id: "a" }]).f).datasets()).toHaveLength(1);
    expect(await new ApiClient(fakeFetch(200, { items: [{ run_id: "r" }], total: 1, limit: 50, offset: 0 }).f).runs()).toHaveLength(1);
  });

  it("sends configuration_id and the Idempotency-Key header when creating a Run", async () => {
    const { f, calls } = fakeFetch(202, { run_id: "r1" });
    await new ApiClient(f).createRun({ configuration_id: "cfg1" }, "key-1");
    const init = calls[0]!.init!;
    expect(calls[0]!.url).toBe("/api/runs");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ configuration_id: "cfg1" });
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBe("key-1");
  });

  it("uploads .py as multipart without forcing a JSON content type", async () => {
    const { f, calls } = fakeFetch(201, { script_id: "s" });
    const file = new File(["CHECK = {}\n"], "my_check.py");
    await new ApiClient(f).uploadScript({ kind: "check", name: "my", file });
    const init = calls[0]!.init!;
    expect(calls[0]!.url).toBe("/api/scripts/upload");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
    const form = init.body as FormData;
    expect(form.get("kind")).toBe("check");
    expect((form.get("file") as File).name).toBe("my_check.py");
  });

  it("encodes ids in paths (no path injection from ids)", async () => {
    const { f, calls } = fakeFetch(200, {});
    await new ApiClient(f).run("../x?y");
    expect(calls[0]!.url).toBe("/api/runs/..%2Fx%3Fy");
  });

  it("treats 503 /ready as not-ready data, not as a crash", async () => {
    const r = await new ApiClient(fakeFetch(503, { ready: false, checks: [] }).f).ready();
    expect(r.ready).toBe(false);
  });
});

describe("helpers", () => {
  it("extracts slot from code_ref", () => {
    expect(slotOfCodeRef("normalize@abcdef123456")).toBe("normalize");
    expect(slotOfCodeRef("check-02@abc")).toBe("check-02");
    expect(slotOfCodeRef(null)).toBeNull();
  });

  const row = (label: string): CheckRow => ({ LABEL: label, SOURCE: "AFTER", ARGUMENT: "", CNT: 1, TOTAL: 2, METRIC: 0.5, APP_IDS: [], RESULT: "FAIL", CONFIDENCE: "HIGH" });
  const ex = (id: string, n: number, status: CheckExecution["execution_status"] = "SUCCEEDED"): CheckExecution => ({
    execution_id: id,
    slot: id,
    script_id: id,
    check_id: id,
    label: id,
    params: {},
    execution_status: status,
    rows_count: n,
    duration_seconds: 0,
  });
  const doc = (checks: CheckRow[], executions: CheckExecution[]): ReportChecks => ({
    report_id: "rep",
    run_id: "run",
    check_run_id: "cr",
    dataset_revision_id: "rev",
    completeness: "COMPLETE",
    summary: {},
    checks,
    diagnostics: [],
    timings_seconds: {},
    executions,
  });

  it("splits flat report rows per execution by rows_count, in order", () => {
    const g = rowsByExecution(doc([row("a"), row("a"), row("c")], [ex("a", 2), ex("b", 0, "ERROR"), ex("c", 1)]))!;
    expect(g.map((x) => x.rows.map((r) => r.LABEL))).toEqual([["a", "a"], [], ["c"]]);
  });

  it("refuses to guess when rows_count does not add up", () => {
    expect(rowsByExecution(doc([row("a")], [ex("a", 2)]))).toBeNull();
  });
});
