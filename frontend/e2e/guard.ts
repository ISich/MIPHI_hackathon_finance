import { test as base, expect } from "@playwright/test";

/** An expected failed HTTP response, scoped to one request shape. */
export interface AllowedFailure {
  method: string;
  url: RegExp;
  status: number;
}

interface BrowserErrors {
  /** Declare an expected failed response for this test (exact method + URL pattern + status). */
  allow(rule: AllowedFailure): void;
}

/**
 * Automatic for every test: uncaught page errors, console.error, failed requests
 * and HTTP >= 400 responses fail the test at teardown unless explicitly allowed
 * with browserErrors.allow({ method, url, status }). Evidence is attached.
 */
export const test = base.extend<{ browserErrors: BrowserErrors }>({
  browserErrors: [
    async ({ page }, use, testInfo) => {
      const allowed: AllowedFailure[] = [];
      const seen: string[] = [];
      const unexpected: string[] = [];
      const isAllowed = (method: string, url: string, status: number) =>
        allowed.some((a) => a.method === method && a.status === status && a.url.test(new URL(url).pathname));
      page.on("pageerror", (e) => unexpected.push(`pageerror: ${e.message}`));
      page.on("console", (m) => {
        if (m.type() !== "error") return;
        // Chromium logs every failed response as "Failed to load resource"; those
        // are judged by the response handler below, which knows method/URL/status.
        if (m.text().startsWith("Failed to load resource")) return;
        unexpected.push(`console.error: ${m.text()}`);
      });
      page.on("requestfailed", (r) => unexpected.push(`requestfailed: ${r.method()} ${r.url()} ${r.failure()?.errorText ?? ""}`));
      page.on("response", (r) => {
        if (r.status() < 400) return;
        const line = `http ${r.status()}: ${r.request().method()} ${r.url()}`;
        seen.push(line);
        if (!isAllowed(r.request().method(), r.url(), r.status())) unexpected.push(line);
      });
      await use({ allow: (rule) => allowed.push(rule) });
      if (seen.length || unexpected.length)
        await testInfo.attach("browser-errors.txt", { body: [...seen, "-- unexpected --", ...unexpected].join("\n"), contentType: "text/plain" });
      expect(unexpected, "unexpected browser errors").toEqual([]);
    },
    { auto: true },
  ],
});
export { expect };
