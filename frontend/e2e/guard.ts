import { test as base, expect } from "@playwright/test";

/** Fails a test on uncaught page errors or console.error; keeps them as evidence. */
export const test = base.extend<{ consoleErrors: string[] }>({
  consoleErrors: async ({ page }, use, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(`console.error: ${m.text()}`);
    });
    page.on("requestfailed", (r) => errors.push(`requestfailed: ${r.method()} ${r.url()} ${r.failure()?.errorText ?? ""}`));
    await use(errors);
    if (errors.length) await testInfo.attach("browser-errors.txt", { body: errors.join("\n"), contentType: "text/plain" });
  },
});
export { expect };
