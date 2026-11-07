// BROWSER SMOKE ON THE DEV MOCK — proves UI behaviour in Chromium, not a real
// calculation. Real backend E2E lives in real.spec.ts.
import { test, expect } from "./guard";
import type { Page } from "@playwright/test";

async function startRun(page: Page) {
  await page.goto("/#/runs/new");
  await expect(page.getByTestId("mock-banner")).toBeVisible();
  await page.getByRole("combobox", { name: "Набор данных" }).selectOption("ds_mock_examples");
  await expect(page.getByRole("combobox", { name: "Процедура normalize" })).toBeVisible();
  await page.getByRole("button", { name: /Сохранить конфигурацию и запустить/ }).click();
  await expect(page).toHaveURL(/#\/runs\/run_/);
  await expect(page.getByTestId("run-status")).toHaveText("COMPLETED", { timeout: 25_000 });
  await expect(page.getByText("Run completed (MOCK)")).toBeVisible();
}

test("configuration → monitor → summary → pivot fallback → drill-down → application → checks", async ({ page, consoleErrors }, info) => {
  await startRun(page);
  await page.getByRole("link", { name: "Сводка" }).click();
  await expect(page.getByTestId("tile-total")).toContainText("6");

  await page.getByRole("link", { name: "Сводная (pivot)" }).click();
  await expect(page.getByTestId("pivot-unavailable")).toContainText("ANALYTICS_UNAVAILABLE");
  const facts = page.getByRole("table", { name: "Базовые факты" });
  await facts.getByRole("link").first().click();
  await expect(page.getByTestId("group-total")).toContainText("полный distinct total backend не сообщает");
  await page.getByRole("link", { name: /^MOCK-/ }).first().click();
  await expect(page.getByRole("table", { name: "Сравнение атрибутов" })).toBeVisible();

  await page.goBack();
  await page.goBack();
  await page.getByRole("link", { name: "Проверки" }).click();
  await expect(page.getByTestId("check-execution")).toHaveCount(5);
  await expect(page.locator('[data-exec-status="ERROR"]')).toContainText("это не FAIL");
  await expect(page.getByTestId("check-summary")).toContainText("ошибок исполнения: 1");
  await page.screenshot({ path: info.outputPath("checks.png"), fullPage: true });
  expect(consoleErrors).toEqual([]);
});

test("new check in builtin-only mode: honest refusal from backend", async ({ page, consoleErrors }) => {
  await startRun(page);
  await page.getByRole("link", { name: "Новая проверка" }).click();
  await expect(page.getByTestId("exec-mode")).toContainText("builtin-only");
  await page.getByRole("button", { name: "Сохранить и запустить проверки" }).click();
  const alert = page.locator('[data-error-code="CUSTOM_EXECUTION_DISABLED"]');
  await expect(alert).toContainText("Исполнение пользовательского Python выключено на сервере");
  // the 403 is an expected, displayed API answer, not a browser error
  expect(consoleErrors.filter((e) => !e.includes("403"))).toEqual([]);
});

test("new check with trusted-local: editor → snapshot → check-run → new report opens", async ({ page, consoleErrors }, info) => {
  await page.addInitScript(() => window.localStorage.setItem("mock.customExecution", "1"));
  await startRun(page);
  await page.getByRole("link", { name: "Новая проверка" }).click();
  await page.getByText("Контракт проверки").click();
  await page.getByRole("button", { name: "Вставить пример" }).click();
  await page.getByLabel("Название").fill("Доля изменённых");
  await page.getByRole("button", { name: "Сохранить и запустить проверки" }).click();
  await expect(page).toHaveURL(/checks\?report=rep_/, { timeout: 15_000 });
  await expect(page.getByTestId("check-execution")).toHaveCount(6);
  await expect(page.getByRole("combobox", { name: "Отчёт" })).toContainText("(повтор проверок)");
  await page.screenshot({ path: info.outputPath("new-check-report.png"), fullPage: true });
  expect(consoleErrors).toEqual([]);
});

test("upload .py in workspace and see it in the procedure slot", async ({ page, consoleErrors }) => {
  await page.goto("/#/scripts/new");
  await page.getByRole("combobox").first().selectOption("normalize");
  await page.getByTestId("py-upload").setInputFiles({ name: "my_norm.py", mimeType: "text/x-python", buffer: Buffer.from("def normalize(d, a, s, p):\n    return []\n") });
  await expect(page.getByTestId("script-source")).toContainText("my_norm.py");
  await page.getByRole("button", { name: "Сохранить snapshot" }).click();
  await expect(page.getByRole("status")).toContainText("Сохранено");
  await page.goto("/#/runs/new");
  await expect(page.getByRole("combobox", { name: "Процедура normalize" })).toContainText("my_norm [file, rev 1]");
  expect(consoleErrors).toEqual([]);
});

test("deep link from HTML report opens the pivot of that Run", async ({ page }) => {
  await page.goto("/runs/run_x/reports/rep_y");
  await expect(page).toHaveURL(/#\/runs\/run_x\/pivot\?report=rep_y/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("run_x");
});
