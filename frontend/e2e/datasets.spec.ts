import ExcelJS from "exceljs";
import { test, expect } from "./guard";

test.beforeEach(async ({ page }) => {
  await page.goto("/#/datasets");
  await page.getByLabel("Логин", { exact: true }).fill("admin");
  await page.getByLabel("Пароль", { exact: true }).fill("admin12345");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Таблицы и сводные", exact: true })).toBeVisible();
});

test("precision-sensitive CSV values survive import, rejected numeric edits, export and reload", async ({ page }) => {
  await page.getByRole("button", { name: "Импорт данных", exact: true }).click();
  await page.getByLabel("Файл таблицы", { exact: true }).setInputFiles({ name: "precision.csv", mimeType: "text/csv", buffer: Buffer.from("Сумма;Исходное значение\n10;1e-400\n20;9007199254740990.5\n") });
  await page.getByRole("button", { name: "Импортировать", exact: true }).click();
  const table = page.getByRole("table", { name: "Данные таблицы", exact: true });
  await expect(table).toContainText("1e-400");
  await expect(table).toContainText("9007199254740990.5");
  for (const value of ["1e-400", "9007199254740990.5"]) {
    await page.getByRole("button", { name: "Изменить: Сумма, строка 1", exact: true }).click();
    const input = page.getByRole("textbox", { name: "Значение: Сумма, строка 1", exact: true });
    await input.fill(value); await input.press("Enter");
    await expect(page.getByRole("alert")).toContainText("поддерживаемой точности");
    await input.press("Escape");
    await expect(page.getByRole("button", { name: "Изменить: Сумма, строка 1", exact: true })).toHaveText("10");
  }
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "CSV", exact: true }).click()]);
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  const exported = Buffer.concat(chunks).toString("utf8");
  expect(exported).toContain("10;1e-400");
  expect(exported).toContain("20;9007199254740990.5");
  await page.reload();
  await expect(table).toContainText("1e-400");
  await expect(table).toContainText("9007199254740990.5");
});

test("import CSV, edit cells, aggregate all rows, export and persist settings", async ({ page }, info) => {
  await page.getByRole("button", { name: "Импорт данных", exact: true }).click();
  await page.getByLabel("Файл таблицы", { exact: true }).setInputFiles({ name: "Портфель.csv", mimeType: "text/csv", buffer: Buffer.from('Регион;Продукт;Сумма\nМосква;Кредит;10\nМосква;Ипотека;20\nКазань;Кредит;90\nКазань;Ипотека;\n') });
  await page.getByRole("button", { name: "Импортировать", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Название таблицы" })).toHaveValue("Портфель");
  await page.getByRole("button", { name: "Изменить: Сумма, строка 1", exact: true }).click();
  const value = page.getByRole("textbox", { name: "Значение: Сумма, строка 1", exact: true });
  await value.fill("40"); await value.press("Enter");
  await page.getByRole("tab", { name: "Сводная таблица", exact: true }).click();
  await page.getByRole("combobox", { name: "Агрегация", exact: true }).selectOption("avg");
  await page.getByRole("group", { name: "Столбцы", exact: false }).getByLabel("Продукт", { exact: false }).check();
  const matrix = page.getByRole("table", { name: "Сводная таблица", exact: true });
  await expect(matrix.locator("tfoot")).toContainText("50");
  await expect(matrix.locator("tbody")).toContainText("Москва");
  await expect(page.getByRole("status").filter({ hasText: "Все изменения сохранены" })).toBeVisible();
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Скачать CSV" }).click()]);
  expect(download.suggestedFilename()).toContain("сводная.csv");
  await page.screenshot({ path: info.outputPath("tables-pivot-light.png"), fullPage: true });
  await page.reload();
  await expect(page.getByRole("textbox", { name: "Название таблицы" })).toHaveValue("Портфель");
  await page.getByRole("tab", { name: "Сводная таблица", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Агрегация", exact: true })).toHaveValue("avg");
  await expect(matrix.locator("tfoot")).toContainText("50");
  await page.getByRole("button", { name: "Включить тёмную тему", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.screenshot({ path: info.outputPath("tables-pivot-dark.png"), fullPage: true });
  expect(await page.locator("body").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
});

test("import an Excel sheet, open backend BEFORE/AFTER and manage rows", async ({ page }) => {
  const workbook = new ExcelJS.Workbook();
  workbook.addWorksheet("Первый").addRows([["Категория", "Число"], ["A", 1]]);
  workbook.addWorksheet("Второй").addRows([["Регион", "Сумма"], ["Москва", 250]]);
  await page.getByRole("button", { name: "Импорт данных", exact: true }).click();
  await page.getByLabel("Файл таблицы", { exact: true }).setInputFiles({ name: "Excel.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from(await workbook.xlsx.writeBuffer()) });
  await page.getByRole("combobox", { name: "Лист Excel", exact: true }).selectOption("1");
  await page.getByRole("button", { name: "Импортировать", exact: true }).click();
  await expect(page.getByRole("table", { name: "Данные таблицы", exact: true })).toContainText("250");
  await page.getByRole("button", { name: "Строка", exact: true }).click();
  await expect(page.getByRole("button", { name: "Изменить: Сумма, строка 2", exact: true })).toBeVisible();
  await page.getByLabel("Выбрать строку 2", { exact: true }).check();
  await page.getByRole("button", { name: "Удалить строки (1)", exact: true }).click();
  await expect(page.getByRole("button", { name: "Изменить: Сумма, строка 2", exact: true })).toHaveCount(0);
  await page.getByRole("combobox", { name: "Версия", exact: true }).selectOption("before");
  await page.getByRole("button", { name: "Открыть как таблицу", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Название таблицы" })).toHaveValue(/BEFORE/);
  await expect(page.getByRole("table", { name: "Данные таблицы", exact: true })).toContainText("400000");
  await page.getByRole("combobox", { name: "Версия", exact: true }).selectOption("after");
  await page.getByRole("button", { name: "Открыть как таблицу", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Название таблицы" })).toHaveValue(/AFTER/);
  await expect(page.getByRole("table", { name: "Данные таблицы", exact: true })).toContainText("450000");
  await page.getByRole("button", { name: "Удалить таблицу", exact: true }).click();
  await page.getByRole("button", { name: "Удалить", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Название таблицы" })).toHaveValue(/BEFORE/);
});
