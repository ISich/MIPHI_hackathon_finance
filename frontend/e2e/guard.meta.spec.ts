// Meta-tests of the browser-error guard (run with the mock suite).
import { test } from "./guard";

test.fail("an unexpected failed API response fails the test even if the test never looks at errors", async ({ page }) => {
  await page.goto("/#/runs");
  await page.evaluate(() => fetch("/api/definitely-not-a-route-xyz").catch(() => undefined));
  await page.waitForTimeout(300);
});

test.fail("an uncaught page error fails the test", async ({ page }) => {
  await page.goto("/#/runs");
  await page.evaluate(() => setTimeout(() => { throw new Error("boom from page"); }, 0));
  await page.waitForTimeout(300);
});
