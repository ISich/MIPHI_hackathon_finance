// BROWSER SMOKE ON THE DEV MOCK — proves UI behaviour in Chromium, not a real
// calculation. Real backend E2E lives in real.spec.ts.
import { test, expect } from "./guard";
import type { Page } from "@playwright/test";
import { signIn } from "./login";

async function startRun(page: Page) {
  await signIn(page, "/#/runs/new");
  await expect(page.getByTestId("mock-banner")).toBeVisible();
  await page.getByRole("combobox", { name: "Набор данных" }).selectOption("ds_mock_examples");
  await expect(page.getByRole("combobox", { name: "Процедура normalize" })).toBeVisible();
  await page.getByRole("button", { name: /Сохранить конфигурацию и запустить/ }).click();
  await expect(page).toHaveURL(/#\/runs\/run_/);
  await expect(page.getByTestId("run-status")).toHaveText("COMPLETED", { timeout: 25_000 });
  await expect(page.getByText("Run completed (MOCK)")).toBeVisible();
}

test("configuration → monitor → summary → pivot → drill-down → application → checks", async ({ page }, info) => {
  await startRun(page);
  await page.getByRole("link", { name: "Сводка" }).click();
  await expect(page.getByTestId("tile-total")).toContainText("6");

  await page.getByRole("link", { name: "Сводная (pivot)" }).click();
  const facts = page.getByRole("table", { name: "Сводная таблица" });
  await facts.getByRole("link").first().click();
  await expect(page.getByTestId("group-total")).toContainText("Всего различных заявок");
  await page.getByRole("link", { name: /^MOCK-/ }).first().click();
  await expect(page.getByRole("table", { name: "Сравнение атрибутов" })).toBeVisible();

  await page.goBack();
  await page.goBack();
  await page.getByRole("link", { name: "Проверки" }).click();
  await expect(page.getByTestId("check-execution")).toHaveCount(5);
  await expect(page.locator('[data-exec-status="ERROR"]')).toContainText("это не FAIL");
  await expect(page.getByTestId("check-summary")).toContainText("ошибок исполнения: 1");
  await page.screenshot({ path: info.outputPath("checks.png"), fullPage: true });
});

test("new check in builtin-only mode: honest refusal from backend", async ({ page }) => {
  await startRun(page);
  await page.getByRole("link", { name: "Новая проверка" }).click();
  await expect(page.getByTestId("exec-mode")).toContainText("builtin-only");
  await page.getByRole("button", { name: "Сохранить и запустить проверки" }).click();
  const alert = page.locator('[data-error-code="CUSTOM_EXECUTION_DISABLED"]');
  await expect(alert).toContainText("Исполнение пользовательского Python выключено на сервере");
});

test("new check with trusted-local: editor → snapshot → check-run → new report opens", async ({ page }, info) => {
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
});

test("upload .py in workspace and see it in the procedure slot", async ({ page }) => {
  await signIn(page, "/#/scripts/new");
  await page.getByRole("combobox").first().selectOption("normalize");
  await page.getByTestId("py-upload").setInputFiles({ name: "my_norm.py", mimeType: "text/x-python", buffer: Buffer.from("def normalize(d, a, s, p):\n    return []\n") });
  await expect(page.getByTestId("script-source")).toContainText("my_norm.py");
  await page.getByRole("button", { name: "Сохранить snapshot" }).click();
  await expect(page.getByRole("status")).toContainText("Сохранено");
  await page.goto("/#/runs/new");
  await expect(page.getByRole("combobox", { name: "Процедура normalize" })).toContainText("my_norm [file, rev 1]");
});

test("deep link from HTML report opens the pivot of that Run", async ({ page }) => {
  await signIn(page, "/runs/run_x/reports/rep_y");
  await expect(page).toHaveURL(/#\/runs\/run_x\/pivot\?report=rep_y/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("run_x");
});

test("per-application HTML link keeps the application and report through sign-in and back navigation", async ({ page }) => {
  await signIn(page, "/runs/run_x/reports/rep_y?app_id=MOCK-0001");
  await expect(page).toHaveURL(/#\/runs\/run_x\/apps\/MOCK-0001\?report=rep_y$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Заявка MOCK-0001");
  await page.getByRole("link", { name: "← К сводной", exact: true }).click();
  await expect(page).toHaveURL(/#\/runs\/run_x\/pivot\?report=rep_y$/);
});

async function sidebarLink(page: Page, name: string) {
  const navigation = page.getByRole("navigation", { name: "Основная навигация" });
  if (!(await navigation.isVisible())) await page.getByRole("button", { name: "Открыть боковую панель" }).click();
  await navigation.getByRole("link", { name, exact: true }).click();
  if ((page.viewportSize()?.width ?? 0) < 760) await expect(navigation).toBeHidden();
}

test("dashboard shows honest empty states and responsive navigation", async ({ page }, info) => {
  await signIn(page, "/#/overview");
  await expect(page.getByRole("heading", { name: "Обзор рабочего пространства" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Всего запусков/ })).toContainText("0");
  await expect(page.getByText("Пока ни одного запуска")).toBeVisible();
  await expect(page.getByRole("img", { name: /Запуски за последние 7 дней/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await sidebarLink(page, "Запуски");
  await expect(page).toHaveURL(/#\/runs$/);
  await sidebarLink(page, "Обзор");
  await expect(page).toHaveURL(/#\/overview$/);
  if ((page.viewportSize()?.width ?? 0) < 760) {
    const trigger = page.getByRole("button", { name: "Открыть боковую панель" });
    await trigger.click();
    await expect(page.getByRole("dialog", { name: "Навигация проекта" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(trigger).toBeFocused();
  }
  await page.screenshot({ path: info.outputPath("dashboard-empty.png"), fullPage: true });
});

test("command palette navigates and theme choice persists", async ({ page }) => {
  await signIn(page, "/#/overview");
  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Быстрый переход" });
  await expect(palette).toBeVisible();
  await palette.getByRole("textbox").fill("Python");
  await palette.getByRole("link", { name: /Рабочая область/ }).click();
  await expect(page).toHaveURL(/#\/scripts$/);
  await expect(palette).not.toBeVisible();
  await page.getByRole("button", { name: "Включить тёмную тему" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Включить светлую тему" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

test("dashboard metrics, search and status filters use returned runs", async ({ page }, info) => {
  await startRun(page);
  await sidebarLink(page, "Запуски");
  const table = page.getByRole("table", { name: "Список запусков" });
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await page.getByRole("searchbox", { name: "Поиск запусков" }).fill("missing-run");
  await expect(page.getByText("Ничего не найдено", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Сбросить фильтры" }).click();
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await page.getByRole("group", { name: "Фильтр статуса" }).getByRole("button", { name: "С ошибкой", exact: true }).click();
  await expect(page.getByText("Ничего не найдено", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /Завершено/ }).click();
  await expect(table.locator("tbody tr")).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await sidebarLink(page, "Обзор");
  await expect(page.getByRole("button", { name: /Всего запусков/ })).toContainText("1");
  await expect(page.getByText("1 за 7 дней", { exact: true })).toBeVisible();
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await page.screenshot({ path: info.outputPath("dashboard-with-run.png"), fullPage: true });
});
