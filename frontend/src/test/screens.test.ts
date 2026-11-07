// Component tests (@vue/test-utils) against the dev mock as a TEST DOUBLE of the
// backend wire format — not the real backend; real E2E is e2e/real.spec.ts.
import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import ErrorView from "../components/ErrorView.vue";
import ProgressBar from "../components/ProgressBar.vue";
import { completedRun, holder, resetMock, testApi } from "./mockApi";
import { alertEl, allByTestId, button, byTestId, choose, click, link, select, table, text, typeInto, upload, waitFor } from "./dom";

vi.mock("../api/instance", async () => {
  const m = await import("./mockApi");
  return { api: m.testApi, IS_MOCK: false };
});

const { default: ChecksView } = await import("../checks-report/ChecksView.vue");
const { default: NewCheck } = await import("../editor/NewCheck.vue");
const { default: RunPage } = await import("../run-monitor/RunPage.vue");
const { default: PivotView } = await import("../pivot/PivotView.vue");
const { default: SummaryView } = await import("../report-summary/SummaryView.vue");
const { default: NewRun } = await import("../run-config/NewRun.vue");
const { default: GroupApplications } = await import("../drilldown/GroupApplications.vue");
const { default: FactApplications } = await import("../drilldown/FactApplications.vue");
const { default: App } = await import("../App.vue");

const mnt = <P extends Record<string, unknown>>(c: Parameters<typeof mount>[0], props?: P) =>
  mount(c, { props, attachTo: document.body.appendChild(document.createElement("div")) });

beforeEach(() => {
  resetMock();
  window.location.hash = "";
});

describe("Run monitor", () => {
  it("polls status/events until COMPLETED and only then enables the report tabs", async () => {
    const cfg = await testApi.createConfiguration({ name: "t", dataset_id: "ds_mock_examples", slots: {} });
    const run = await testApi.createRun({ configuration_id: cfg.config_id }, "k1");
    const w = mnt(RunPage, { runId: run.run_id, query: new URLSearchParams() });
    await waitFor(() => byTestId(w, "run-status"));
    const summaryTab = () => [...document.querySelectorAll(".tabs > *")].find((e) => e.textContent === "Сводка")!;
    expect(summaryTab().tagName).toBe("SPAN");
    await waitFor(() => expect(summaryTab().tagName).toBe("A"), 3000);
    expect(text(w)).toContain("Run completed (MOCK)");
    const evCalls = holder.calls.filter((c) => c.url.includes("/events?after="));
    expect(evCalls.some((c) => !c.url.endsWith("after=0"))).toBe(true);
    const seqs = [...table(w, "Журнал событий").querySelectorAll("tr")].map((r) => r.querySelector("td")!.textContent);
    expect(new Set(seqs).size).toBe(seqs.length);
    w.unmount();
  });

  it("does not show a run's data under another run id after switching (stale responses dropped)", async () => {
    const a = await completedRun();
    const b = await completedRun();
    // Responses for run A arrive late (after the user already switched to B).
    const inner = holder.fetch;
    holder.fetch = async (url, init) => {
      if (url.includes(a.run_id)) await new Promise((r) => setTimeout(r, 80));
      return inner(url, init);
    };
    const w = mnt(RunPage, { runId: a.run_id, tab: "monitor", query: new URLSearchParams() });
    await new Promise((r) => setTimeout(r, 10)); // A's request is in flight
    await w.setProps({ runId: b.run_id } as never);
    await waitFor(() => expect(byTestId(w, "run-status").textContent).toBe("COMPLETED"));
    await new Promise((r) => setTimeout(r, 150)); // let A's late response land
    expect(document.querySelector("h1")!.textContent).toContain(b.run_id);
    expect(text(w)).toContain(b.initial_report_id);
    expect(text(w)).not.toContain(a.initial_report_id);
    w.unmount();
  });
});

describe("Progress", () => {
  it("never invents a percent when total is unknown", () => {
    const w = mnt(ProgressBar, { processed: 5, total: null });
    expect(text(w)).not.toContain("%");
    expect(text(w)).toContain("всего неизвестно");
    w.unmount();
  });
  it("shows percent when total is known", () => {
    const w = mnt(ProgressBar, { processed: 1, total: 4 });
    expect(text(w)).toContain("25%");
    w.unmount();
  });
});

describe("Summary", () => {
  it("shows not-ready instead of an empty successful summary for an unfinished Run", async () => {
    const cfg = await testApi.createConfiguration({ name: "t", dataset_id: "ds_mock_examples", slots: {} });
    const run = await testApi.createRun({ configuration_id: cfg.config_id }, "k2");
    const w = mnt(SummaryView, { run });
    const alert = await waitFor(() => alertEl(w));
    expect(alert.textContent).toContain("Ещё не готово");
    expect(alert.dataset.errorCode).toBe("NOT_READY");
    w.unmount();
  });
  it("renders numbers returned by the backend for a completed Run", async () => {
    const run = await completedRun();
    const w = mnt(SummaryView, { run });
    await waitFor(() => expect(byTestId(w, "tile-total").textContent).toContain("6"));
    expect(byTestId(w, "tile-changed").textContent).toContain("4");
    w.unmount();
  });
});

describe("Checks", () => {
  it("distinguishes PASS, FAIL, muted LOW, 0-row success and execution errors", async () => {
    const run = await completedRun();
    const w = mnt(ChecksView, { run, reportId: null });
    const cards = await waitFor(() => {
      const c = allByTestId(w, "check-execution");
      expect(c).toHaveLength(5);
      return c;
    });
    const err = cards.find((c) => c.dataset.execStatus === "ERROR")!;
    expect(err.textContent).toContain("ошибка исполнения: ERROR");
    expect(err.textContent).toContain("это не FAIL");
    expect(err.textContent).toContain("KeyError");
    expect(err.querySelector(".badge-fail")).toBeNull();
    expect(text(w)).toContain("0 строк результата (это не PASS)");
    const lowRows = document.querySelectorAll('tr[data-confidence="LOW"]');
    expect(lowRows.length).toBe(2);
    lowRows.forEach((r) => expect(r.classList.contains("low")).toBe(true));
    expect(byTestId(w, "check-summary").textContent).toContain("ошибок исполнения: 1");
    expect(byTestId(w, "check-summary").textContent).toContain("INCOMPLETE");
    expect(text(w)).toContain("1 пример(ов) из 2");
    w.unmount();
  });

  it("opens the explicitly requested report, not an implicit latest", async () => {
    const run = await completedRun();
    const w = mnt(ChecksView, { run, reportId: run.initial_report_id });
    await waitFor(() => expect(allByTestId(w, "check-execution").length).toBeGreaterThan(0));
    expect(holder.calls.some((c) => c.url === `/api/reports/${run.initial_report_id}/checks`)).toBe(true);
    expect(link(w, "Скачать HTML-отчёт").getAttribute("href")).toBe(`/api/reports/${run.initial_report_id}/checks.html`);
    w.unmount();
  });
});

describe("New check", () => {
  it("in builtin-only mode saves the snapshot but shows the backend's honest refusal", async () => {
    const run = await completedRun();
    const w = mnt(NewCheck, { run });
    await waitFor(() => expect(byTestId(w, "exec-mode").textContent).toContain("builtin-only"));
    await waitFor(() => expect(button(w, "Сохранить и запустить проверки").disabled).toBe(false));
    await click(button(w, "Сохранить и запустить проверки"));
    const alert = await waitFor(() => alertEl(w));
    expect(alert.dataset.errorCode).toBe("CUSTOM_EXECUTION_DISABLED");
    expect(alert.textContent).toContain("Исполнение пользовательского Python выключено на сервере");
    expect(window.location.hash).toBe("");
    expect(text(w)).toContain("Скрипт уже сохранён");
    w.unmount();
  });

  it("with trusted-local: editor code → snapshot → check-run → opens the NEW report_id", async () => {
    resetMock({ customExecution: true });
    const run = await completedRun();
    const w = mnt(NewCheck, { run });
    const editor = await waitFor(() => {
      const t = document.querySelector<HTMLTextAreaElement>("textarea.code")!;
      expect(t.value).toContain("CHECK");
      return t;
    });
    await typeInto(editor, "CHECK = {}");
    await click(button(w, "Сохранить и запустить проверки"));
    await waitFor(() => expect(window.location.hash).toMatch(/checks\?report=rep_/), 3000);
    const newReport = decodeURIComponent(window.location.hash.split("report=")[1]!);
    expect(newReport).not.toBe(run.initial_report_id);
    const post = holder.calls.find((c) => c.url.endsWith("/check-runs"))!;
    expect(JSON.parse(String(post.init!.body)).checks).toHaveLength(6); // 5 original + the new one in one common report
    expect((post.init!.headers as Record<string, string>)["Idempotency-Key"]).toBeTruthy();
    const created = holder.calls.find((c) => c.url === "/api/scripts" && c.init?.method === "POST")!;
    expect(JSON.parse(String(created.init!.body))).toMatchObject({ kind: "check", code: "CHECK = {}" });
    w.unmount();
  });

  it("an uploaded .py is sent as source=file via multipart upload", async () => {
    resetMock({ customExecution: true });
    const run = await completedRun();
    const w = mnt(NewCheck, { run });
    const input = await waitFor(() => byTestId(w, "py-upload") as HTMLInputElement);
    const file = new File(["def run(m, p=None):\n    return []\n\nCHECK = {'id': 'x', 'label': 'x', 'params': {}, 'entrypoint': run}\n"], "my_check.py", { type: "text/x-python" });
    await upload(input, file);
    await waitFor(() => expect(byTestId(w, "script-source").textContent).toContain("my_check.py"));
    await click(button(w, "Сохранить и запустить проверки"));
    await waitFor(() => expect(window.location.hash).toMatch(/checks\?report=/), 3000);
    const up = holder.calls.find((c) => c.url === "/api/scripts/upload")!;
    expect(up.init!.body).toBeInstanceOf(FormData);
    w.unmount();
  });

  it("rejects a non-.py upload in the browser", async () => {
    const run = await completedRun();
    const w = mnt(NewCheck, { run });
    const input = await waitFor(() => byTestId(w, "py-upload") as HTMLInputElement);
    await upload(input, new File(["x"], "evil.sh"));
    await waitFor(() => expect(text(w)).toContain("Нужен файл .py"));
    w.unmount();
  });
});

describe("Pivot", () => {
  it("shows the honest 501 reason and falls back to D4 base facts without totals", async () => {
    const run = await completedRun();
    const w = mnt(PivotView, { run, query: new URLSearchParams("rows=PATH") });
    await waitFor(() => expect(byTestId(w, "pivot-unavailable").textContent).toContain("ANALYTICS_UNAVAILABLE"));
    const t = await waitFor(() => table(w, "Базовые факты"));
    expect(t.textContent).not.toContain("Итого");
    const a = t.querySelector("a")!;
    expect(a.getAttribute("href")).toMatch(/fact-apps\?g=/);
    expect(decodeURIComponent(a.getAttribute("href")!)).toContain('"SOURCE"');
    w.unmount();
  });

  it("with a server rollup: renders distinct counts/totals from the server and links cells via opaque locators", async () => {
    resetMock({ serverPivot: true });
    const run = await completedRun();
    const w = mnt(PivotView, { run, query: new URLSearchParams("rows=PATH&cols=SOURCE&f.DIFF_FLAG=1") });
    const t = await waitFor(() => table(w, "Сводная таблица"));
    const req = holder.calls.find((c) => c.url.endsWith("/pivot"))!;
    expect(JSON.parse(String(req.init!.body))).toMatchObject({ rows: ["PATH"], cols: ["SOURCE"], filters: [{ dim: "DIFF_FLAG", op: "in", values: ["1"] }] });
    // grand total = distinct apps with any diff (4), not the sum of cells
    expect(t.querySelector('[data-testid="grand-total"]')!.textContent).toContain("4");
    expect(t.querySelector("a")!.getAttribute("href")).toMatch(new RegExp(`#/runs/${run.run_id}/groups/[^?]+\\?back=`));
    w.unmount();
  });

  it("changing the layout in the controls updates the URL (server recomputes)", async () => {
    resetMock({ serverPivot: true });
    const run = await completedRun();
    const w = mnt(PivotView, { run, query: new URLSearchParams("rows=PATH") });
    await waitFor(() => table(w, "Сводная таблица"));
    await choose(select(w, "Добавить колонку"), "SOURCE");
    expect(window.location.hash).toBe(`#/runs/${run.run_id}/pivot?rows=PATH&cols=SOURCE`);
    w.unmount();
  });

  it("drill-down page shows the full distinct total, not the page length", async () => {
    resetMock({ serverPivot: true });
    const run = await completedRun();
    const p = await testApi.pivot(run.run_id, { rows: [], cols: [], filters: [] });
    const w = mnt(GroupApplications, { runId: run.run_id, group: p.grand_total.group, back: "rows=PATH" });
    await waitFor(() => expect(byTestId(w, "group-total").textContent).toContain("Всего различных заявок: 6"));
    expect(link(w, /К сводной/).getAttribute("href")).toBe(`#/runs/${run.run_id}/pivot?rows=PATH`);
    w.unmount();
  });

  it("fact drill-down says when the backend gives no full total", async () => {
    const run = await completedRun();
    const group = JSON.stringify({ PATH: "decision.result.decision", SOURCE: "AFTER", VALUE_ADJUSTED: "APPROVE", DIFF_FLAG: 0, ARRAY_KEY: "" });
    const w = mnt(FactApplications, { runId: run.run_id, group, cnt: 3 });
    await waitFor(() => expect(byTestId(w, "group-total").textContent).toContain("полный distinct total backend не сообщает"));
    w.unmount();
  });
});

describe("New run form", () => {
  it("creates configuration + Run and navigates to its monitor; double submit creates one Run", async () => {
    const w = mnt(NewRun);
    await waitFor(() => select(w, "Набор данных").querySelectorAll("option").length > 1 || (() => { throw new Error("no datasets yet"); })());
    await choose(select(w, "Набор данных"), "ds_mock_examples");
    await waitFor(() => select(w, "Процедура normalize"));
    const form = document.querySelector("form")!;
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    await waitFor(() => expect(window.location.hash).toMatch(/^#\/runs\/run_/));
    expect(holder.calls.filter((c) => c.url === "/api/runs" && c.init?.method === "POST")).toHaveLength(1);
    w.unmount();
  });
});

describe("Safety", () => {
  it("renders values from data as text, never as HTML", () => {
    const w = mnt(ErrorView, { error: new ApiError(422, { code: "X", message: '<img src=x onerror="alert(1)">', details: { v: "<script>alert(1)</script>" } }) });
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
    expect(alertEl(w).textContent).toContain('<img src=x onerror="alert(1)">');
    w.unmount();
  });

  it("App does not show the MOCK banner outside mock mode", () => {
    const w = mnt(App);
    expect(document.querySelector('[data-testid="mock-banner"]')).toBeNull();
    w.unmount();
  });
});
