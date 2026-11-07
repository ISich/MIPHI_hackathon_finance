// REAL E2E: UI dev server (proxy) → running backend-night → pinned decision_diff
// core. Run with PLAYWRIGHT_BASE_URL set (see README). Numbers are compared
// with what the backend API itself returns, never with constants.
import { test, expect } from "./guard";
import type { APIRequestContext, Page } from "@playwright/test";

const TRUSTED = process.env.E2E_TRUSTED === "1";

async function api<T>(request: APIRequestContext, path: string): Promise<T> {
  const r = await request.get(path);
  expect(r.ok(), `${path} → ${r.status()}`).toBeTruthy();
  return (await r.json()) as T;
}

async function startRealRun(page: Page): Promise<string> {
  await page.goto("/#/runs/new");
  await expect(page.getByTestId("mock-banner")).toHaveCount(0);
  const ds = page.getByRole("combobox", { name: "Набор данных" });
  await expect(ds.locator("option", { hasText: "core fixture" })).toHaveCount(1);
  await ds.selectOption({ label: (await ds.locator("option", { hasText: "core fixture" }).textContent())!.trim() });
  await page.getByRole("button", { name: /Сохранить конфигурацию и запустить/ }).click();
  await expect(page).toHaveURL(/#\/runs\/run_/);
  const runId = decodeURIComponent(page.url().split("#/runs/")[1]!.split(/[/?]/)[0]!);
  await expect(page.getByTestId("run-status")).toHaveText(/COMPLETED|FAILED/, { timeout: 150_000 });
  await expect(page.getByTestId("run-status")).toHaveText("COMPLETED");
  return runId;
}

test("real: configuration → Run → monitor/events → summary → pivot → drill-down → application → checks", async ({ page }, info) => {
  // page.request shares the browser cookie = the same anonymous owner session
  const request = page.request;
  const runId = await startRealRun(page);
  // journal shows real stage events with code snapshot links
  const journal = page.getByRole("table", { name: "Журнал событий" });
  await expect(journal).toContainText("NORMALIZING");
  await journal.getByText(/^код normalize$/).first().click();
  await expect(page.locator("pre.code-view").first()).toContainText("sha256");
  await page.screenshot({ path: info.outputPath("real-monitor.png"), fullPage: true });

  const summary = await api<{ total_apps: number; changed_apps: number; decision_changed_apps: number }>(request, `/api/runs/${runId}/summary`);
  await page.getByRole("link", { name: "Сводка" }).click();
  await expect(page.getByTestId("tile-total")).toContainText(String(summary.total_apps));
  await expect(page.getByTestId("tile-changed")).toContainText(String(summary.changed_apps));
  await expect(page.getByTestId("tile-decision")).toContainText(String(summary.decision_changed_apps));

  await page.getByRole("link", { name: "Сводная (pivot)" }).click();
  const table = page.getByRole("table", { name: "Сводная таблица" });
  await expect(table).toBeVisible();
  const pending = page.waitForResponse(r => r.url().endsWith(`/api/runs/${runId}/pivot`) && r.request().method() === "POST");
  await page.getByRole("combobox", { name: "Добавить колонку" }).selectOption("CHANGE_TYPE");
  const response = await pending;
  expect(response.status()).toBe(200);
  expect(response.request().postDataJSON()).toEqual({ dimensions: ["DIFF_FLAG", "CHANGE_TYPE"], filters: {}, limit: 100, offset: 0 });
  const pivot = await response.json();
  expect(pivot.items.length).toBeGreaterThan(0);
  await expect(table.getByRole("link")).toHaveCount(pivot.items.length);
  const first = pivot.items[0];
  const cell = table.locator(`a[href*="${encodeURIComponent(first.group_locator)}"]`);
  await expect(cell).toHaveText(String(first.cnt));
  await cell.click();
  await expect(page.getByTestId("group-total")).toContainText(`Всего различных заявок: ${first.cnt}`);
  const appLink = page.locator(".app-list a").first();
  await expect(appLink).toBeVisible();
  await appLink.click();
  await expect(page.getByRole("table", { name: "Сравнение атрибутов" })).toBeVisible();

  await page.goto(`/#/runs/${encodeURIComponent(runId)}/checks`);
  const run = await api<{ initial_report_id: string }>(request, `/api/runs/${runId}`);
  const doc = await api<{ executions: Array<{ execution_status: string }> }>(request, `/api/reports/${run.initial_report_id}/checks`);
  const cards = page.getByTestId("check-execution");
  await expect(cards).toHaveCount(doc.executions.length);
  for (const [i, e] of doc.executions.entries()) await expect(cards.nth(i)).toHaveAttribute("data-exec-status", e.execution_status);
  await page.screenshot({ path: info.outputPath("real-checks.png"), fullPage: true });

  const html = await request.get(`/api/reports/${run.initial_report_id}/checks.html`);
  expect(html.ok()).toBeTruthy();
  expect(await html.text()).toContain(`/runs/${runId}/reports/${run.initial_report_id}`);
});

test("real: an open terminal Run monitor receives a later builtin CheckRun and report without reload", async ({ page }) => {
  const runId = await startRealRun(page);
  const request = page.request;
  const run = await api<{ config_id: string }>(request, `/api/runs/${runId}`);
  const config = await api<{ checks: Array<{ script_id: string }> }>(request, `/api/configurations/${run.config_id}`);
  const response = await request.post(`/api/runs/${runId}/check-runs`, {
    headers: { "Idempotency-Key": `late-monitor-${Date.now()}` }, data: { checks: config.checks },
  });
  expect(response.status()).toBe(202);
  const accepted = await response.json();
  await expect.poll(async () => (await api<{ status: string }>(request, `/api/check-runs/${accepted.check_run_id}`)).status, { timeout: 120_000 }).toBe("COMPLETED");
  const events = await api<{ items: Array<{ seq: number; check_run_id: string | null }> }>(request, `/api/runs/${runId}/events?after=0`);
  const late = events.items.filter(e => e.check_run_id === accepted.check_run_id);
  expect(late.length).toBeGreaterThan(0);
  const journal = page.getByRole("table", { name: "Журнал событий" });
  for (const event of late) await expect(journal.locator("tr").filter({ has: page.locator("td:first-child", { hasText: new RegExp(`^${event.seq}$`) }) })).toHaveCount(1);
  await expect(page.getByRole("link", { name: `${accepted.report_id} — PUBLISHED`, exact: true })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`#/runs/${runId}`));
});

test("real: a fresh browser gets exactly one anonymous session on first load (no parallel-session race)", async ({ page }) => {
  const issued: string[] = [];
  page.on("response", async (r) => {
    const sc = (await r.allHeaders())["set-cookie"];
    if (sc && sc.includes("dd_session=")) issued.push(r.url());
  });
  await page.goto("/#/scripts/new"); // fires several API calls at once
  await expect(page.getByTestId("exec-mode")).toBeVisible();
  await page.goto("/#/runs/new");
  await expect(page.getByRole("combobox", { name: "Процедура normalize" })).toBeVisible();
  expect(issued).toHaveLength(1);
  expect(issued[0]).toContain("/api/session");
});

test("real: another session cannot read this Run (owner scope)", async ({ page, request }) => {
  const runId = await startRealRun(page);
  expect((await page.request.get(`/api/runs/${runId}`)).status()).toBe(200);
  const foreign = await request.get(`/api/runs/${runId}`); // separate cookie jar = other session
  expect(foreign.status()).toBe(404);
  expect((await foreign.json()).code).toBe("NOT_FOUND");
});

test("real: new check — builtin-only refusal or trusted-local new report", async ({ page, browserErrors }, info) => {
  // page.request shares the browser cookie = the same anonymous owner session
  const request = page.request;
  if (!TRUSTED) browserErrors.allow({ method: "POST", url: /^\/api\/runs\/[^/]+\/check-runs$/, status: 403 }); // documented refusal in builtin-only
  const runId = await startRealRun(page);
  await page.getByRole("link", { name: "Новая проверка" }).click();
  await page.getByText("Контракт проверки").click();
  await page.getByRole("button", { name: "Вставить пример" }).click();
  await page.getByLabel("Название").fill("e2e changed share");
  await page.getByRole("button", { name: "Сохранить и запустить проверки" }).click();
  if (!TRUSTED) {
    await expect(page.getByTestId("exec-mode")).toContainText("builtin-only");
    await expect(page.locator('[data-error-code="CUSTOM_EXECUTION_DISABLED"]')).toContainText("выключено на сервере");
    return;
  }
  await expect(page).toHaveURL(/checks\?report=/, { timeout: 120_000 });
  const reportId = decodeURIComponent(page.url().split("report=")[1]!);
  const run = await api<{ initial_report_id: string }>(request, `/api/runs/${runId}`);
  expect(reportId).not.toBe(run.initial_report_id);
  const doc = await api<{ executions: Array<{ check_id: string | null }> }>(request, `/api/reports/${reportId}/checks`);
  expect(doc.executions.some((e) => e.check_id === "changed_share")).toBeTruthy();
  await expect(page.getByTestId("check-execution")).toHaveCount(doc.executions.length);
  // initial report unchanged
  const initial = await api<{ executions: unknown[] }>(request, `/api/reports/${run.initial_report_id}/checks`);
  expect(initial.executions.length).toBe(doc.executions.length - 1);
  await page.screenshot({ path: info.outputPath("real-new-check.png"), fullPage: true });
});

test("real: modified procedure (workspace normalize) → new Run uses the new snapshot", async ({ page, browserErrors }) => {
  const request = page.request;
  if (!TRUSTED) browserErrors.allow({ method: "POST", url: /^\/api\/runs$/, status: 403 });
  // 1. workspace script from the backend's own normalize example
  await page.goto("/#/scripts/new");
  await page.getByRole("combobox").first().selectOption("normalize");
  await page.getByRole("button", { name: "Вставить пример" }).click();
  const name = `e2e normalize ${Date.now()}`;
  await page.getByLabel("Название").fill(name);
  await page.getByRole("button", { name: "Сохранить snapshot" }).click();
  await expect(page.getByRole("status")).toContainText("Сохранено");
  // 2. configuration with that script in the normalize slot
  await page.goto("/#/runs/new");
  const ds = page.getByRole("combobox", { name: "Набор данных" });
  await ds.selectOption({ label: (await ds.locator("option", { hasText: "core fixture" }).textContent())!.trim() });
  const slot = page.getByRole("combobox", { name: "Процедура normalize" });
  await slot.selectOption({ label: (await slot.locator("option", { hasText: name }).textContent())!.trim() });
  await page.getByRole("button", { name: /Сохранить конфигурацию и запустить/ }).click();
  if (!TRUSTED) {
    await expect(page.locator('[data-error-code="CUSTOM_EXECUTION_DISABLED"]')).toContainText("выключено на сервере");
    expect(page.url()).toContain("#/runs/new");
    return;
  }
  await expect(page).toHaveURL(/#\/runs\/run_/);
  const runId = decodeURIComponent(page.url().split("#/runs/")[1]!.split(/[/?]/)[0]!);
  await expect(page.getByTestId("run-status")).toHaveText("COMPLETED", { timeout: 150_000 });
  const snap = await api<{ source: string; name: string }>(request, `/api/runs/${runId}/code/normalize`);
  expect(snap.source).toBe("workspace");
  expect(snap.name).toBe(name);
});
