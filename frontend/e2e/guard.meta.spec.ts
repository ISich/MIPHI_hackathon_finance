// Self-tests of the browser-error guard (run with the mock suite). They assert
// exactly what the guard recorded instead of test.fail(), so an unrelated
// failure cannot make them pass.
import { expect, test } from "./guard";

test("an unexpected failed API response is recorded as a failure even if the test never looks at errors", async ({ page, browserErrors }) => {
  await page.goto("/#/runs");
  await page.evaluate(() => fetch("/api/definitely-not-a-route-xyz").catch(() => undefined));
  await expect.poll(() => browserErrors.takeUnexpected().join("\n"), { timeout: 5000 }).toMatch(/GET http:\/\/[^ ]+\/api\/definitely-not-a-route-xyz/);
});

test("an uncaught page error is recorded as a failure", async ({ page, browserErrors }) => {
  await page.goto("/#/runs");
  await page.evaluate(() => setTimeout(() => { throw new Error("boom from page"); }, 0));
  await expect.poll(() => browserErrors.takeUnexpected().join("\n"), { timeout: 5000 }).toContain("pageerror: boom from page");
});

test("an explicitly allowed failure (method + URL + status) is not recorded", async ({ page, browserErrors }) => {
  await page.goto("/#/runs");
  const status = await page.evaluate(() => fetch("/api/definitely-not-a-route-xyz").then((r) => r.status, () => -1));
  browserErrors.allow({ method: "GET", url: /^\/api\/definitely-not-a-route-xyz$/, status });
  await page.evaluate(() => fetch("/api/definitely-not-a-route-xyz").catch(() => undefined));
  await page.waitForTimeout(200);
  const left = browserErrors.takeUnexpected();
  // only the first, not-yet-allowed request is recorded
  expect(left.filter((l) => l.includes("definitely-not-a-route-xyz"))).toHaveLength(1);
});
