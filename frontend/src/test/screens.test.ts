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
const { default: RunsList } = await import("../run-monitor/RunsList.vue");
const { default: DatasetPivot } = await import("../datasets/DatasetPivot.vue");
const { default: DataGrid } = await import("../datasets/DataGrid.vue");
const { fromMatrix } = await import("../datasets/model");
const { default: GroupApplications } = await import("../drilldown/GroupApplications.vue");
const { default: FactApplications } = await import("../drilldown/FactApplications.vue");
const { default: App } = await import("../App.vue");

const mnt = <P extends Record<string, unknown>>(c: Parameters<typeof mount>[0], props?: P) =>
  mount(c, { props, attachTo: document.body.appendChild(document.createElement("div")) });

beforeEach(() => {
  resetMock();
  window.location.hash = "";
});

describe("Account dashboard totals", () => {
  it("shows the API total and labels status counts, search and activity as a partial page", async () => {
    const run = await completedRun();
    const inner = holder.fetch;
    holder.fetch = async (url, init) => url === "/api/runs"
      ? new Response(JSON.stringify({ items: Array.from({ length: 50 }, (_, i) => ({ ...run, run_id: `run_${i}` })), total: 121, limit: 50, offset: 0 }), { status: 200 })
      : inner(url, init);
    const w = mnt(RunsList, { overview: true });
    await waitFor(() => expect(w.find(".metric-neutral .metric-value").text()).toBe("121"));
    expect(w.find(".metric-success .metric-value").text()).toBe("50");
    expect(w.find(".metric-success .metric-detail").text()).toBe("Среди последних 50");
    expect(w.get('[role="note"]').text()).toContain("Загружены последние 50 из 121");
    expect(w.get('[role="img"]').attributes("aria-label")).toContain("По последним 50 запускам");
    expect(w.get('.table-footer [role="status"]').text()).toBe("Показано 50 из 121");
    w.unmount();
  });

  it("does not show a partial-page warning when the whole account fits in one page", async () => {
    await completedRun();
    const w = mnt(RunsList);
    await waitFor(() => expect(w.find(".metric-neutral .metric-value").text()).toBe("1"));
    expect(w.find('[role="note"]').exists()).toBe(false);
    expect(w.get(".metric-success .metric-detail").text()).toBe("Все запуски аккаунта");
    w.unmount();
  });
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

describe("Run journal longer than one events page", () => {
  it("receives late check events and the published report in an already-open terminal monitor", async () => {
    const run = await completedRun();
    const w = mnt(RunPage, { runId: run.run_id, tab: "monitor", query: new URLSearchParams() });
    await waitFor(() => expect(byTestId(w, "run-status").textContent).toBe("COMPLETED"));
    const cfg = await testApi.configuration(run.config_id);
    let cr = await testApi.createCheckRun(run.run_id, { checks: cfg.checks }, "late-check");
    for (let i = 0; i < 10 && cr.status !== "COMPLETED"; i++) cr = await testApi.checkRun(cr.check_run_id);
    expect(cr.status).toBe("COMPLETED");
    await waitFor(() => expect(table(w, "Журнал событий").textContent).toContain("executed (MOCK)"));
    await waitFor(() => expect(link(w, new RegExp(cr.report_id)).textContent).toContain("PUBLISHED"));
    w.unmount();
  });
  it("drains the whole event backlog at a terminal status", async () => {
    resetMock({ eventsPageLimit: 3, extraEventsPerStage: 8 });
    const cfg = await testApi.createConfiguration({ name: "t", dataset_id: "ds_mock_examples", slots: {} });
    const run = await testApi.createRun({ configuration_id: cfg.config_id }, "k-long");
    const w = mnt(RunPage, { runId: run.run_id, tab: "monitor", query: new URLSearchParams() });
    await waitFor(() => expect(byTestId(w, "run-status").textContent).toBe("COMPLETED"), 4000);
    await new Promise((r) => setTimeout(r, 50));
    // ground truth: page through the same API
    let after = 0;
    const all: number[] = [];
    for (;;) {
      const p = await testApi.events(run.run_id, after);
      if (!p.items.length) break;
      all.push(...p.items.map((e) => e.seq));
      after = p.next_after;
    }
    expect(all.length).toBeGreaterThan(40);
    const shown = [...table(w, "Журнал событий").querySelectorAll("tr")].map((r) => Number(r.querySelector("td")!.textContent));
    expect(shown).toEqual(all);
    expect(text(w)).toContain("Run completed (MOCK)");
    w.unmount();
  });
});

describe("Code links of later CheckRuns", () => {
  it("an event of a later CheckRun opens that CheckRun's code snapshot, not the Run's original slot", async () => {
    resetMock({ customExecution: true });
    const run = await completedRun();
    const script = await testApi.createScript({ kind: "check", name: "later check", code: "# LATER CHECK CODE\nCHECK = {}\n" });
    const cfg = await testApi.configuration(run.config_id);
    let cr = await testApi.createCheckRun(run.run_id, { checks: [...cfg.checks, { script_id: script.script_id }] }, "k-cr");
    for (let i = 0; i < 10 && cr.status !== "COMPLETED"; i++) cr = await testApi.checkRun(cr.check_run_id);
    const w = mnt(RunPage, { runId: run.run_id, tab: "monitor", query: new URLSearchParams() });
    const summary = await waitFor(() => {
      const s = [...document.querySelectorAll("summary")].find((x) => x.textContent === "код check-06");
      if (!s) throw new Error("no check-06 link yet");
      return s;
    });
    (summary.parentElement as HTMLDetailsElement).open = true;
    summary.parentElement!.dispatchEvent(new Event("toggle"));
    await waitFor(() => expect(text(w)).toContain("# LATER CHECK CODE"));
    expect(holder.calls.some((c) => c.url === `/api/check-runs/${cr.check_run_id}/code/check-06`)).toBe(true);
    expect(holder.calls.some((c) => c.url === `/api/runs/${run.run_id}/code/check-06`)).toBe(false);
    w.unmount();
  });
});

describe("Explicit report context survives navigation", () => {
  it("an application opened from HTML shows attributes and returns to the same report's pivot", async () => {
    const run = await completedRun();
    window.location.hash = `#/runs/${run.run_id}/apps/MOCK-0001?report=rep_X`;
    await testApi.login("admin", "admin12345");
    const w = mnt(App);
    await waitFor(() => table(w, "Сравнение атрибутов"));
    expect(w.get("h1").text()).toBe("Заявка MOCK-0001");
    expect(link(w, /К сводной/).getAttribute("href")).toBe(`#/runs/${run.run_id}/pivot?report=rep_X`);
    w.unmount();
  });
  it("run tabs keep ?report=", async () => {
    const run = await completedRun();
    const w = mnt(RunPage, { runId: run.run_id, tab: "checks", query: new URLSearchParams("report=rep_X") });
    await waitFor(() => expect(link(w, "Сводная (pivot)").getAttribute("href")).toBe(`#/runs/${run.run_id}/pivot?report=rep_X`));
    expect(link(w, "Мониторинг").getAttribute("href")).toBe(`#/runs/${run.run_id}/monitor?report=rep_X`);
    w.unmount();
  });

  it("pivot drill-down and its way back keep ?report=", async () => {
    resetMock({ serverPivot: true });
    const run = await completedRun();
    const w = mnt(PivotView, { run, query: new URLSearchParams("rows=PATH&report=rep_X") });
    const t = await waitFor(() => table(w, "Сводная таблица"));
    const back = new URLSearchParams(t.querySelector("a")!.getAttribute("href")!.split("?")[1]).get("back")!;
    expect(new URLSearchParams(back).get("report")).toBe("rep_X");
    expect(new URLSearchParams(back).get("rows")).toBe("PATH");
    w.unmount();
  });

  it("base-facts drill-down keeps ?report= on the way back", async () => {
    resetMock({ serverPivot: false });
    const run = await completedRun();
    const w = mnt(PivotView, { run, query: new URLSearchParams("report=rep_X") });
    const t = await waitFor(() => table(w, "Базовые факты"));
    const href = t.querySelector("a")!.getAttribute("href")!;
    expect(new URLSearchParams(href.split("?")[1]).get("report")).toBe("rep_X");
    w.unmount();
    const g = new URLSearchParams(href.split("?")[1]);
    const w2 = mnt(FactApplications, { runId: run.run_id, group: g.get("g")!, cnt: 1, report: "rep_X" });
    expect(link(w2, /К базовым фактам/).getAttribute("href")).toBe(`#/runs/${run.run_id}/pivot?report=rep_X`);
    w2.unmount();
  });
});

describe("Dataset pivot calculation errors", () => {
  it.each(["1e-400", "9007199254740990.5"])("rejects an edit to %s without changing the existing numeric cell", async value => {
    const dataset = fromMatrix("numbers", [["Сумма"], [10]], "test");
    const w = mount(DataGrid, { props: { dataset } });
    await w.get('[aria-label="Изменить: Сумма, строка 1"]').trigger("click");
    const input = w.get('input[aria-label="Значение: Сумма, строка 1"]');
    await input.setValue(value);
    await input.trigger("keydown.enter");
    expect(w.get('[role="alert"]').text()).toContain("поддерживаемой точности");
    expect(w.emitted("change")).toBeUndefined();
    expect(dataset.rows).toEqual([[10]]);
    expect((input.element as HTMLInputElement).value).toBe(value);
    await input.trigger("keydown.esc");
    expect(w.get('[aria-label="Изменить: Сумма, строка 1"]').text()).toBe("10");
    w.unmount();
  });

  it("shows an unsafe subtotal as an error, blocks export and recovers with another aggregation", async () => {
    const dataset = fromMatrix("groups", [["Group", "Value"], ["A", Number.MAX_SAFE_INTEGER], ["A", 2], ["B", -Number.MAX_SAFE_INTEGER]], "test");
    const w = mount(DatasetPivot, { props: { dataset }, attachTo: document.body.appendChild(document.createElement("div")) });
    expect(w.get('[role="alert"]').text()).toContain("диапазон точного расчёта");
    expect(button(w, "Скачать CSV").disabled).toBe(true);
    expect(w.find('[aria-label="Сводная таблица"]').exists()).toBe(false);
    await w.setProps({ dataset: { ...dataset, pivot: { ...dataset.pivot, operation: "count" } } });
    expect(w.find('[role="alert"]').exists()).toBe(false);
    expect(button(w, "Скачать CSV").disabled).toBe(false);
    expect(table(w, "Сводная таблица").textContent).toContain("3");
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

  it("shows the AI opinion as a separate block: request -> pending -> ready with fact refs", async () => {
    const run = await completedRun();
    const w = mnt(ChecksView, { run, reportId: null });
    const panel = await waitFor(() => {
      const p = byTestId(w, "ai-opinion");
      expect(p.dataset.aiStatus).toBe("NOT_REQUESTED");
      return p;
    });
    expect(panel.textContent).toContain("не меняет результаты проверок");
    await click(button(w, "Получить мнение ИИ"));
    expect(holder.calls.some((c) => c.init?.method === "POST" && c.url === `/api/reports/${run.initial_report_id}/ai-opinion`)).toBe(true);
    await waitFor(() => expect(byTestId(w, "ai-opinion").dataset.aiStatus).toBe("READY"), 8000);
    expect(byTestId(w, "ai-opinion").textContent).toContain("Малая выборка");
    expect(byTestId(w, "ai-opinion").querySelector('code.ai-ref[title*="check_row"]')).not.toBeNull();
    expect(allByTestId(w, "check-execution")).toHaveLength(5);
    w.unmount();
  }, 15000);

  it("opens the explicitly requested report, not an implicit latest", async () => {
    const run = await completedRun();
    const w = mnt(ChecksView, { run, reportId: run.initial_report_id });
    await waitFor(() => expect(allByTestId(w, "check-execution").length).toBeGreaterThan(0));
    expect(holder.calls.some((c) => c.url === `/api/reports/${run.initial_report_id}/checks`)).toBe(true);
    expect(link(w, "Скачать HTML-отчёт").getAttribute("href")).toBe(`/api/reports/${run.initial_report_id}/checks.html`);
    w.unmount();
  });
});

describe("Checks report belongs to the displayed Run", () => {
  it("refuses to show Run B's report under Run A (?report=<B report>)", async () => {
    const a = await completedRun();
    const b = await completedRun();
    const w = mnt(ChecksView, { run: a, reportId: b.initial_report_id });
    await waitFor(() => expect(document.querySelector('[data-error-code="REPORT_RUN_MISMATCH"]')).not.toBeNull());
    expect(allByTestId(w, "check-execution")).toHaveLength(0);
    expect(text(w)).toContain(b.initial_report_id);
    w.unmount();
  });

  it("refuses a report whose data revision differs from the Run's", async () => {
    const run = await completedRun();
    const inner = holder.fetch;
    holder.fetch = async (url, init) => {
      const r = await inner(url, init);
      if (!url.endsWith(`/reports/${run.initial_report_id}/checks`)) return r;
      const body = await r.json();
      return new Response(JSON.stringify({ ...body, dataset_revision_id: "rev_other" }), { status: 200 });
    };
    const w = mnt(ChecksView, { run, reportId: null });
    await waitFor(() => expect(document.querySelector('[data-error-code="REPORT_RUN_MISMATCH"]')).not.toBeNull());
    expect(allByTestId(w, "check-execution")).toHaveLength(0);
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
    await waitFor(() => expect(button(w, "Сохранить и запустить проверки").disabled).toBe(false));
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
    await waitFor(() => expect(button(w, "Сохранить и запустить проверки").disabled).toBe(false));
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
  it("maps sparse items with null/empty coordinates and pages without inventing zeroes", async () => {
    const run = await completedRun();
    const inner = holder.fetch;
    holder.fetch = async (url, init) => {
      if (!url.endsWith("/pivot")) return inner(url, init);
      const req = JSON.parse(String(init!.body));
      const items = req.offset === 0 ? [
        { dimensions: { PATH: null, SOURCE: "BEFORE" }, cnt: 7, group_locator: "opaque.1" },
        { dimensions: { PATH: "", SOURCE: "AFTER" }, cnt: 3, group_locator: "opaque.2" },
      ] : [{ dimensions: { PATH: "last", SOURCE: "AFTER" }, cnt: 2, group_locator: "opaque.3" }];
      return new Response(JSON.stringify({ run_id: run.run_id, data_revision: run.dataset_revision_id, items, total: 101, limit: 100, offset: req.offset }), { status: 200 });
    };
    const w = mnt(PivotView, { run, query: new URLSearchParams("rows=PATH&cols=SOURCE&report=rep_ctx") });
    const t = await waitFor(() => table(w, "Сводная таблица"));
    expect([...t.querySelectorAll("a")].map(a => a.textContent)).toEqual(["7", "3"]);
    expect(t.textContent).toContain("∅ (пусто)");
    expect(t.querySelectorAll("td .muted")).toHaveLength(2);
    expect(t.textContent).not.toContain("Итого");
    await click(button(w, "Далее →"));
    await waitFor(() => expect(table(w, "Сводная таблица").textContent).toContain("last"));
    const calls = holder.calls.filter(c => c.url.endsWith("/pivot"));
    expect(JSON.parse(String(calls.at(-1)!.init!.body))).toEqual({ dimensions: ["PATH", "SOURCE"], filters: {}, limit: 100, offset: 100 });
    await w.setProps({ query: new URLSearchParams("rows=SOURCE") } as never);
    await waitFor(() => expect(JSON.parse(String(holder.calls.filter(c => c.url.endsWith("/pivot")).at(-1)!.init!.body)).offset).toBe(0));
    w.unmount();
  });
  it("shows 422 with its details and never presents it as unavailable or empty success", async () => {
    const run = await completedRun();
    const inner = holder.fetch;
    holder.fetch = async (url, init) => url.endsWith("/pivot")
      ? new Response(JSON.stringify({ code: "VALIDATION_ERROR", message: "Bad dimensions", details: { field: "dimensions" }, request_id: "req-422" }), { status: 422 })
      : inner(url, init);
    const w = mnt(PivotView, { run, query: new URLSearchParams() });
    await waitFor(() => expect(alertEl(w).textContent).toContain("HTTP 422"));
    expect(text(w)).toContain("req-422");
    expect(text(w)).toContain("dimensions");
    expect(w.find('[data-testid="pivot-unavailable"]').exists()).toBe(false);
    expect(w.find('table').exists()).toBe(false);
    w.unmount();
  });

  it("rejects the old rows/cols payload in the contract mock", async () => {
    const run = await completedRun();
    await expect(testApi.request("POST", `/api/runs/${run.run_id}/pivot`, { body: { rows: ["PATH"], cols: [], filters: [] } })).rejects.toMatchObject({ status: 422 });
  });
  it("shows the honest 501 reason and falls back to D4 base facts without totals", async () => {
    resetMock({ serverPivot: false });
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

  it("renders distinct cell counts from the server and links cells via opaque locators", async () => {
    resetMock({ serverPivot: true });
    const run = await completedRun();
    const w = mnt(PivotView, { run, query: new URLSearchParams("rows=PATH&cols=SOURCE&f.DIFF_FLAG=1") });
    const t = await waitFor(() => table(w, "Сводная таблица"));
    const req = holder.calls.find((c) => c.url.endsWith("/pivot"))!;
    expect(JSON.parse(String(req.init!.body))).toEqual({ dimensions: ["PATH", "SOURCE"], filters: { DIFF_FLAG: ["1"] }, limit: 100, offset: 0 });
    expect(t.textContent).not.toContain("Итого");
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
    const p = await testApi.pivot(run.run_id, { dimensions: ["SOURCE"], filters: {} });
    const w = mnt(GroupApplications, { runId: run.run_id, group: p.items[0]!.group_locator, back: "rows=PATH" });
    await waitFor(() => expect(byTestId(w, "group-total").textContent).toContain(`Всего различных заявок: ${p.items[0]!.cnt}`));
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

describe("Prerequisite loads gate submission (no silent empty check sets)", () => {
  const wrap = (rule: (url: string) => Promise<Response | null> | null) => {
    const inner = holder.fetch;
    holder.fetch = async (url, init) => (await rule(url)) ?? inner(url, init);
  };
  const posts = (path: string) => holder.calls.filter((c) => c.url === path && c.init?.method === "POST");

  it("NewRun: cannot submit while /scripts is still loading (would send checks: [] and disable server defaults)", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    wrap((url) => (url.startsWith("/api/scripts") ? gate.then(() => null) : null));
    const w = mnt(NewRun);
    await waitFor(() => expect(select(w, "Набор данных").options.length).toBeGreaterThan(1));
    await choose(select(w, "Набор данных"), "ds_mock_examples");
    expect(button(w, /Сохранить конфигурацию и запустить/).disabled).toBe(true);
    document.querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await new Promise((r) => setTimeout(r, 30));
    expect(posts("/api/configurations")).toHaveLength(0);
    release();
    await waitFor(() => expect(button(w, /Сохранить конфигурацию и запустить/).disabled).toBe(false));
    w.unmount();
  });

  it("NewRun: a failed /scripts load is shown and blocks submission", async () => {
    wrap((url) => (url.startsWith("/api/scripts") ? Promise.resolve(new Response(JSON.stringify({ code: "INTERNAL_ERROR", message: "boom", details: {}, request_id: "r" }), { status: 500 })) : null));
    const w = mnt(NewRun);
    await waitFor(() => expect(document.querySelector('[data-error-code="INTERNAL_ERROR"]')).not.toBeNull());
    await choose(select(w, "Набор данных"), "ds_mock_examples");
    expect(button(w, /Сохранить конфигурацию и запустить/).disabled).toBe(true);
    document.querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await new Promise((r) => setTimeout(r, 30));
    expect(posts("/api/configurations")).toHaveLength(0);
    w.unmount();
  });

  it("NewCheck: with 'include existing' on, a failed configuration load is shown and blocks the check-run", async () => {
    resetMock({ customExecution: true });
    const run = await completedRun();
    wrap((url) => (url.startsWith("/api/configurations/") ? Promise.resolve(new Response(JSON.stringify({ code: "INTERNAL_ERROR", message: "cfg boom", details: {}, request_id: "r" }), { status: 500 })) : null));
    const w = mnt(NewCheck, { run });
    await waitFor(() => expect(document.querySelector('[data-error-code="INTERNAL_ERROR"]')?.textContent).toContain("cfg boom"));
    await waitFor(() => expect(document.querySelector<HTMLTextAreaElement>("textarea.code")!.value).toContain("CHECK"));
    expect(button(w, "Сохранить и запустить проверки").disabled).toBe(true);
    await click(button(w, "Сохранить и запустить проверки"));
    expect(posts("/api/scripts")).toHaveLength(0);
    expect(holder.calls.some((c) => c.url.endsWith("/check-runs"))).toBe(false);
    // explicitly opting out of the original checks is allowed
    const include = [...document.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')].find((i) => i.parentElement!.textContent!.includes("исходные проверки"))!;
    include.click();
    await waitFor(() => expect(button(w, "Сохранить и запустить проверки").disabled).toBe(false));
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
