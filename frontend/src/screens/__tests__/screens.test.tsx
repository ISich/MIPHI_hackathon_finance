// Component tests against the dev mock as a TEST DOUBLE of the backend wire
// format (not the real backend; real E2E is a separate, explicitly reported step).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { completedRun, holder, resetMock, testApi } from "../../test/mockApi";
import { Progress } from "../../components/Progress";
import { ErrorView } from "../../components/StateView";
import { ApiError } from "../../api/client";

vi.mock("../../api/instance", async () => {
  const m = await import("../../test/mockApi");
  return { api: m.testApi, IS_MOCK: false };
});

const { ChecksView } = await import("../ChecksView");
const { NewCheck } = await import("../NewCheck");
const { RunPage } = await import("../RunPage");
const { PivotView } = await import("../PivotView");
const { SummaryView } = await import("../SummaryView");
const { NewRun } = await import("../NewRun");
const { FactApplications, GroupApplications } = await import("../Drilldown");
const { App } = await import("../../App");

beforeEach(() => {
  resetMock();
  window.location.hash = "";
});

describe("Run monitor", () => {
  it("polls status/events until COMPLETED and only then enables the report tabs", async () => {
    const cfg = await testApi.createConfiguration({ name: "t", dataset_id: "ds_mock_examples", slots: {} });
    const run = await testApi.createRun({ configuration_id: cfg.config_id }, "k1");
    render(<RunPage runId={run.run_id} tab={undefined} query={new URLSearchParams()} />);
    await screen.findByTestId("run-status");
    // before completion the summary tab is not a link
    expect(screen.getByText("Сводка").tagName).toBe("SPAN");
    await waitFor(() => expect(screen.getByRole("link", { name: "Сводка" })).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByText(/Run completed \(MOCK\)/)).toBeInTheDocument();
    // events are requested incrementally with ?after=
    const evCalls = holder.calls.filter((c) => c.url.includes("/events?after="));
    expect(evCalls.some((c) => !c.url.endsWith("after=0"))).toBe(true);
    // each event seq rendered exactly once (no duplicates from overlapping polls)
    const rows = within(screen.getByRole("table", { name: "Журнал событий" })).getAllByRole("row");
    const seqs = rows.map((r) => r.querySelector("td")!.textContent);
    expect(new Set(seqs).size).toBe(seqs.length);
  });

  it("does not show a run's data under another run id after switching (stale responses dropped)", async () => {
    const a = await completedRun();
    const b = await completedRun();
    const { rerender } = render(<RunPage runId={a.run_id} tab="monitor" query={new URLSearchParams()} />);
    rerender(<RunPage runId={b.run_id} tab="monitor" query={new URLSearchParams()} />);
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(b.run_id));
    await waitFor(() => expect(screen.getByTestId("run-status")).toHaveTextContent("COMPLETED"));
    expect(screen.getByText(b.initial_report_id, { exact: false })).toBeInTheDocument();
    expect(screen.queryByText(a.initial_report_id, { exact: false })).toBeNull();
  });
});

describe("Progress", () => {
  it("never invents a percent when total is unknown", () => {
    render(<Progress processed={5} total={null} />);
    expect(screen.queryByText(/%/)).toBeNull();
    expect(screen.getByText(/всего неизвестно/)).toBeInTheDocument();
  });
  it("shows percent when total is known", () => {
    render(<Progress processed={1} total={4} />);
    expect(screen.getByText(/25%/)).toBeInTheDocument();
  });
});

describe("Summary", () => {
  it("shows not-ready instead of an empty successful summary for an unfinished Run", async () => {
    const cfg = await testApi.createConfiguration({ name: "t", dataset_id: "ds_mock_examples", slots: {} });
    const run = await testApi.createRun({ configuration_id: cfg.config_id }, "k2");
    render(<SummaryView run={run} />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Ещё не готово");
    expect(alert).toHaveAttribute("data-error-code", "NOT_READY");
  });
  it("renders numbers returned by the backend for a completed Run", async () => {
    const run = await completedRun();
    render(<SummaryView run={run} />);
    expect(await screen.findByTestId("tile-total")).toHaveTextContent("6");
    expect(screen.getByTestId("tile-changed")).toHaveTextContent("4");
  });
});

describe("Checks", () => {
  it("distinguishes PASS, FAIL, muted LOW, 0-row success and execution errors", async () => {
    const run = await completedRun();
    render(<ChecksView run={run} reportId={null} />);
    const cards = await screen.findAllByTestId("check-execution");
    expect(cards).toHaveLength(5);
    const err = cards.find((c) => c.dataset.execStatus === "ERROR")!;
    expect(err).toHaveTextContent("ошибка исполнения: ERROR");
    expect(err).toHaveTextContent("это не FAIL");
    expect(err).toHaveTextContent("KeyError");
    expect(within(err).queryByText("FAIL")).toBeNull();
    expect(screen.getByText(/0 строк результата \(это не PASS\)/)).toBeInTheDocument();
    const lowRows = document.querySelectorAll('tr[data-confidence="LOW"]');
    expect(lowRows.length).toBe(2);
    lowRows.forEach((r) => expect(r).toHaveClass("low"));
    expect(screen.getByTestId("check-summary")).toHaveTextContent("ошибок исполнения: 1");
    expect(screen.getByTestId("check-summary")).toHaveTextContent("INCOMPLETE");
    // K examples are labelled against CNT, not presented as the population
    expect(screen.getAllByText(/1 пример\(ов\) из 2/).length).toBeGreaterThan(0);
  });

  it("opens the explicitly requested report, not an implicit latest", async () => {
    const run = await completedRun();
    render(<ChecksView run={run} reportId={run.initial_report_id} />);
    await screen.findAllByTestId("check-execution");
    expect(holder.calls.some((c) => c.url === `/api/reports/${run.initial_report_id}/checks`)).toBe(true);
    expect(screen.getByRole("link", { name: "Скачать HTML-отчёт" })).toHaveAttribute("href", `/api/reports/${run.initial_report_id}/checks.html`);
  });
});

describe("New check", () => {
  it("in builtin-only mode saves the snapshot but shows the backend's honest refusal", async () => {
    const run = await completedRun();
    render(<NewCheck run={run} />);
    expect(await screen.findByTestId("exec-mode")).toHaveTextContent("builtin-only");
    await userEvent.click(await screen.findByRole("button", { name: "Сохранить и запустить проверки" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveAttribute("data-error-code", "CUSTOM_EXECUTION_DISABLED");
    expect(alert).toHaveTextContent("Исполнение пользовательского Python выключено на сервере");
    expect(window.location.hash).toBe("");
    expect(screen.getByText(/Скрипт уже сохранён/)).toBeInTheDocument();
  });

  it("with trusted-local: editor code → snapshot → check-run → opens the NEW report_id", async () => {
    resetMock({ customExecution: true });
    const run = await completedRun();
    render(<NewCheck run={run} />);
    const editor = await screen.findByLabelText("Код проверки");
    await userEvent.clear(editor);
    await userEvent.type(editor, "CHECK = {{}");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить и запустить проверки" }));
    await waitFor(() => expect(window.location.hash).toMatch(/checks\?report=rep_/), { timeout: 3000 });
    const newReport = decodeURIComponent(window.location.hash.split("report=")[1]!);
    expect(newReport).not.toBe(run.initial_report_id);
    const post = holder.calls.find((c) => c.url.endsWith("/check-runs"))!;
    const body = JSON.parse(String(post.init!.body));
    expect(body.checks).toHaveLength(6); // 5 original + the new one in one common report
    expect((post.init!.headers as Record<string, string>)["Idempotency-Key"]).toBeTruthy();
    const created = holder.calls.find((c) => c.url === "/api/scripts" && c.init?.method === "POST")!;
    expect(JSON.parse(String(created.init!.body))).toMatchObject({ kind: "check", code: "CHECK = {}" });
  });

  it("an uploaded .py is sent as source=file via multipart upload", async () => {
    resetMock({ customExecution: true });
    const run = await completedRun();
    render(<NewCheck run={run} />);
    const input = await screen.findByTestId("py-upload");
    const file = new File(["def run(m, p=None):\n    return []\n\nCHECK = {'id': 'x', 'label': 'x', 'params': {}, 'entrypoint': run}\n"], "my_check.py", { type: "text/x-python" });
    await userEvent.upload(input, file);
    expect(await screen.findByTestId("script-source")).toHaveTextContent("my_check.py");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить и запустить проверки" }));
    await waitFor(() => expect(window.location.hash).toMatch(/checks\?report=/), { timeout: 3000 });
    const upload = holder.calls.find((c) => c.url === "/api/scripts/upload")!;
    expect(upload.init!.body).toBeInstanceOf(FormData);
  });

  it("rejects a non-.py upload in the browser", async () => {
    const run = await completedRun();
    render(<NewCheck run={run} />);
    const input = await screen.findByTestId("py-upload");
    await userEvent.upload(input, new File(["x"], "evil.sh"), { applyAccept: false });
    expect(await screen.findByText(/Нужен файл \.py/)).toBeInTheDocument();
  });
});

describe("Pivot", () => {
  it("shows the honest 501 reason and falls back to D4 base facts without totals", async () => {
    const run = await completedRun();
    render(<PivotView run={run} query={new URLSearchParams("rows=PATH")} />);
    const note = await screen.findByTestId("pivot-unavailable");
    expect(note).toHaveTextContent("ANALYTICS_UNAVAILABLE");
    const table = await screen.findByRole("table", { name: "Базовые факты" });
    expect(within(table).queryByText("Итого")).toBeNull();
    const link = within(table).getAllByRole("link")[0]!;
    expect(link.getAttribute("href")).toMatch(/fact-apps\?g=/);
    expect(decodeURIComponent(link.getAttribute("href")!)).toContain('"SOURCE"');
  });

  it("with a server rollup: renders distinct counts/totals from the server and links cells via opaque locators", async () => {
    resetMock({ serverPivot: true });
    const run = await completedRun();
    render(<PivotView run={run} query={new URLSearchParams("rows=PATH&cols=SOURCE&f.DIFF_FLAG=1")} />);
    const table = await screen.findByRole("table", { name: "Сводная таблица" });
    const req = holder.calls.find((c) => c.url.endsWith("/pivot"))!;
    expect(JSON.parse(String(req.init!.body))).toMatchObject({ rows: ["PATH"], cols: ["SOURCE"], filters: [{ dim: "DIFF_FLAG", op: "in", values: ["1"] }] });
    // grand total = distinct apps with any diff (4), not the sum of cells
    expect(within(table).getByTestId("grand-total")).toHaveTextContent("4");
    const cellLink = within(table).getAllByRole("link")[0]!;
    expect(cellLink.getAttribute("href")).toMatch(new RegExp(`#/runs/${run.run_id}/groups/[^?]+\\?back=`));
  });

  it("drill-down page shows the full distinct total, not the page length", async () => {
    resetMock({ serverPivot: true });
    const run = await completedRun();
    const p = await testApi.pivot(run.run_id, { rows: [], cols: [], filters: [] });
    render(<GroupApplications runId={run.run_id} group={p.grand_total.group} back="rows=PATH" />);
    expect(await screen.findByTestId("group-total")).toHaveTextContent("Всего различных заявок: 6");
    expect(screen.getByRole("link", { name: /К сводной/ })).toHaveAttribute("href", `#/runs/${run.run_id}/pivot?rows=PATH`);
  });

  it("fact drill-down says when the backend gives no full total", async () => {
    const run = await completedRun();
    const group = JSON.stringify({ PATH: "decision.result.decision", SOURCE: "AFTER", VALUE_ADJUSTED: "APPROVE", DIFF_FLAG: 0, ARRAY_KEY: "" });
    render(<FactApplications runId={run.run_id} group={group} cnt={3} />);
    expect(await screen.findByTestId("group-total")).toHaveTextContent("полный distinct total backend не сообщает");
  });
});

describe("New run form", () => {
  it("creates configuration + Run and navigates to its monitor; double click creates one Run", async () => {
    render(<NewRun />);
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Набор данных" }), "ds_mock_examples");
    await screen.findByRole("combobox", { name: "Процедура normalize" });
    const btn = screen.getByRole("button", { name: /Сохранить конфигурацию и запустить/ });
    await userEvent.dblClick(btn);
    await waitFor(() => expect(window.location.hash).toMatch(/^#\/runs\/run_/));
    expect(holder.calls.filter((c) => c.url === "/api/runs" && c.init?.method === "POST")).toHaveLength(1);
  });
});

describe("Safety", () => {
  it("renders values from data as text, never as HTML", () => {
    render(<ErrorView error={new ApiError(422, { code: "X", message: '<img src=x onerror="alert(1)">', details: { v: "<script>alert(1)</script>" } })} />);
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByRole("alert")).toHaveTextContent('<img src=x onerror="alert(1)">');
  });

  it("App does not show the MOCK banner outside mock mode", () => {
    render(<App />);
    expect(screen.queryByTestId("mock-banner")).toBeNull();
  });
});
