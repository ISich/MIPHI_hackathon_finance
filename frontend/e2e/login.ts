import { expect, type Page } from "@playwright/test";

export async function signIn(page: Page, path = "/#/runs") {
  await page.goto(path);
  await page.getByLabel("Логин", { exact: true }).fill(process.env.E2E_USERNAME ?? "admin");
  await page.getByLabel("Пароль", { exact: true }).fill(process.env.E2E_PASSWORD ?? "admin12345");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.locator(".dashboard-header")).toBeVisible();
}
