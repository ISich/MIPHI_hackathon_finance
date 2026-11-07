import { defineConfig, devices } from "@playwright/test";

// Two suites:
//  - e2e/mock.spec.ts: browser smoke against the DEV MOCK (vite --mode mock).
//    Proves the UI flow in a real browser, NOT a real calculation.
//  - e2e/real.spec.ts: real backend E2E; runs only when PLAYWRIGHT_BASE_URL
//    points at a UI dev server proxied to a running backend (npm run e2e:real).
const real = !!process.env.PLAYWRIGHT_BASE_URL;
const MOCK_PORT = 5174;

export default defineConfig({
  testDir: "e2e",
  testMatch: real ? ["real.spec.ts", "auth.spec.ts", "session.spec.ts"] : ["mock.spec.ts", "auth.spec.ts", "guard.meta.spec.ts", "datasets.spec.ts"],
  timeout: real ? 180_000 : 60_000,
  expect: { timeout: real ? 60_000 : 5_000 },
  retries: 1,
  workers: 1,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  outputDir: "test-results",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? `http://127.0.0.1:${MOCK_PORT}`,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1366, height: 900 } } },
    { name: "narrow", use: { ...devices["Pixel 7"] } },
  ],
  webServer: real
    ? undefined
    : {
        command: `npx vite --mode mock --host 127.0.0.1 --port ${MOCK_PORT} --strictPort`,
        url: `http://127.0.0.1:${MOCK_PORT}`,
        reuseExistingServer: false,
        timeout: 60_000,
      },
});
