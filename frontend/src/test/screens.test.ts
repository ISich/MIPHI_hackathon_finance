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
const { default: RunsList } = await import("../run-monitor/RunsList.vue");
const { default: ApplicationView } = await import("../drilldown/ApplicationView.vue");
const { default: NewScript } = await import("../editor/NewScript.vue");

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

describe("Run journal longer than one events page", () => {
  it("drains the whole event backlog before polling stops at a terminal status", async () => {
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

describe("Later CheckRun events reach an already open monitor", () => {
  async function laterCheckRun(runId: string, configId: string) {
    const script = await testApi.createScript({ kind: "check", name: "late check", code: "CHECK = {}\n" });
    const cfg = await testApi.configuration(configId);
    let cr = await testApi.createCheckRun(runId, { checks: [...cfg.checks, { script_id: script.script_id }] }, `k-${Math.random()}`);
    for (let i = 0; i < 10 && cr.status !== "COMPLETED"; i++) cr = await testApi.checkRun(cr.check_run_id);
    return cr;
  }

  it("while the monitor stays open on a terminal Run", async () => {
    resetMock({ customExecution: true });
    const run = await completedRun();
    const w = mnt(RunPage, { runId: run.run_id, tab: "monitor", query: new URLSearchParams() });
    await waitFor(() => expect(text(w)).toContain("Run completed (MOCK)"));
    await new Promise((r) => setTimeout(r, 30)); // polling has settled on the terminal Run
    await laterCheckRun(run.run_id, run.config_id);
    await waitFor(() => expect(text(w)).toContain("Check late check executed (MOCK)"), 2000);
    w.unmount();
  });

  it("after leaving the monitor tab and coming back (same mounted RunPage)", async () => {
    resetMock({ customExecution: true });
    const run = await completedRun();
    const w = mnt(RunPage, { runId: run.run_id, tab: "monitor", query: new URLSearchParams() });
    await waitFor(() => expect(text(w)).toContain("Run completed (MOCK)"));
    await w.setProps({ tab: "new-check" } as never);
    await laterCheckRun(run.run_id, run.config_id);
    await w.setProps({ tab: "monitor" } as never);
    await waitFor(() => expect(text(w)).toContain("Check late check executed (MOCK)"), 2000);
    const link = [...document.querySelectorAll("summary")].find((x) => x.textContent === "код check-06");
    expect(link).toBeTruthy();
    w.unmount();
  });
});

describe("Runs list with responses slower than the poll interval", () => {
  it("still updates (a reload is not started while the previous one is in flight)", async () => {
    const cfg = await testApi.createConfiguration({ name: "t", dataset_id: "ds_mock_examples", slots: {} });
    const queued = await testApi.createRun({ configuration_id: cfg.config_id }, "k-list");
    const inner = holder.fetch;
    holder.fetch = async (url, init) => {
      if (url === "/api/runs") await new Promise((r) => setTimeout(r, 40)); // >> listPollMs (5 ms)
      return inner(url, init);
    };
    const w = mnt(RunsList);
    await waitFor(() => expect(table(w, "Список запусков").textContent).toContain("QUEUED"));
    let r = queued;
    for (let i = 0; i < 20 && r.status !== "COMPLETED"; i++) r = await testApi.run(queued.run_id);
    await waitFor(() => expect(table(w, "Список запусков").textContent).toContain("COMPLETED"), 2000);
    const listCalls = holder.calls.filter((c) => c.url === "/api/runs").length;
    expect(listCalls).toBeLessThan(80); // no request storm
    w.unmount();
  });
});

describe("Report context survives the application card", () => {
  const retOf = (a: Element) => new URLSearchParams(a.getAttribute("href")!.split("?")[1]).get("ret");

  it("application links in checks carry the way back to the same report", async () => {
    const run = await completedRun();
    const w = mnt(ChecksView, { run, reportId: run.initial_report_id });
    const a = await waitFor(() => {
      const x = document.querySelector("a.app-chip");
      if (!x) throw new Error("no app link");
      return x;
    });
    expect(retOf(a)).toBe(`#/runs/${run.run_id}/checks?report=${run.initial_report_id}`);
    w.unmount();
  });

  it("application links of a fact drill-down carry the way back incl. report", async () => {
    const run = await completedRun();
    const group = JSON.stringify({ PATH: "decision.result.decision", SOURCE: "AFTER", VALUE_ADJUSTED: "APPROVE", DIFF_FLAG: 0, ARRAY_KEY: "" });
    const w = mnt(FactApplications, { runId: run.run_id, group, cnt: 3, report: "rep_X" });
    const a = await waitFor(() => {
      const x = document.querySelector(".app-list a");
      if (!x) throw new Error("no app link");
      return x;
    });
    const ret = retOf(a)!;
    expect(ret.startsWith(`#/runs/${run.run_id}/fact-apps?`)).toBe(true);
    expect(new URLSearchParams(ret.split("?")[1]).get("report")).toBe("rep_X");
    w.unmount();
  });

  it("the application card returns to the given place of the same Run only", async () => {
    const run = await completedRun();
    const ret = `#/runs/${run.run_id}/checks?report=rep_X`;
    const w = mnt(ApplicationView, { runId: run.run_id, appId: "MOCK-0001", group: null, back: "", ret });
    expect(link(w, /^←/).getAttribute("href")).toBe(ret);
    w.unmount();
    for (const bad of ["#/runs/other_run/checks", "javascript:alert(1)", "https://evil.example/"]) {
      const w2 = mnt(ApplicationView, { runId: run.run_id, appId: "MOCK-0001", group: null, back: "", ret: bad });
      expect(link(w2, /^←/).getAttribute("href")).toBe(`#/runs/${run.run_id}/pivot`);
      w2.unmount();
    }
  });
});

describe("Base-facts fallback names what it could not apply", () => {
  it("lists the URL filters and layout that the fallback does not apply", async () => {
    const run = await completedRun();
    const w = mnt(PivotView, { run, query: new URLSearchParams("rows=PATH&cols=SOURCE&f.PATH=score.okb.value&f.DIFF_FLAG=1") });
    const note = await waitFor(() => byTestId(w, "unapplied-layout"));
    expect(note.textContent).toContain("PATH ∈ score.okb.value");
    expect(note.textContent).toContain("DIFF_FLAG ∈ 1");
    expect(note.textContent).toContain("Строки: PATH");
    expect(note.textContent).toContain("Колонки: SOURCE");
    w.unmount();
  });

  it("says nothing extra when the URL has no layout or filters", async () => {
    const run = await completedRun();
    const w = mnt(PivotView, { run, query: new URLSearchParams("") });
    await waitFor(() => table(w, "Базовые факты"));
    expect(document.querySelector('[data-testid="unapplied-layout"]')).toBeNull();
    w.unmount();
  });
});

describe("Copying a script requires its source", () => {
  const scriptPosts = () => holder.calls.filter((c) => (c.url === "/api/scripts" || c.url === "/api/scripts/upload") && c.init?.method === "POST");

  it("a failed source load is shown and saving is blocked (no unrelated template saved)", async () => {
    const inner = holder.fetch;
    holder.fetch = async (url, init) =>
      url === "/api/scripts/scr_missing"
        ? new Response(JSON.stringify({ code: "NOT_FOUND", message: "script not found", details: {}, request_id: "r" }), { status: 404 })
        : inner(url, init);
    const w = mnt(NewScript, { fromId: "scr_missing" });
    await waitFor(() => expect(document.querySelector('[data-error-code="NOT_FOUND"]')).not.toBeNull());
    await waitFor(() => button(w, "Сохранить snapshot"));
    expect(button(w, "Сохранить snapshot").disabled).toBe(true);
    await click(button(w, "Сохранить snapshot"));
    expect(scriptPosts()).toHaveLength(0);
    w.unmount();
  });

  it("while the source is loading, the editor does not offer the default template for saving", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const inner = holder.fetch;
    holder.fetch = async (url, init) => {
      if (url === "/api/scripts/scr_check_attribute_new_loss") await gate;
      return inner(url, init);
    };
    const w = mnt(NewScript, { fromId: "scr_check_attribute_new_loss" });
    await waitFor(() => button(w, "Сохранить snapshot"));
    const nameInput = [...document.querySelectorAll("label")].find((l) => l.textContent!.trim().startsWith("Название"))!.querySelector("input")!;
    await typeInto(nameInput, "my copy"); // a name alone must not allow saving the default template
    expect(button(w, "Сохранить snapshot").disabled).toBe(true);
    release();
    await waitFor(() => expect(document.querySelector<HTMLTextAreaElement>("textarea.code")!.value).toContain("MOCK builtin source of check_attribute_new_loss"));
    expect(button(w, "Сохранить snapshot").disabled).toBe(false);
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
