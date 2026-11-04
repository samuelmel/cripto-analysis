import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  expect: {
    timeout: 30_000,
  },
  use: {
    baseURL: "http://127.0.0.1:8000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  webServer: {
    command: "uv run python -m src.api",
    cwd: "..",
    url: "http://127.0.0.1:8000/api/v1/health",
    reuseExistingServer: true,
    timeout: 120_000,
    env: {
      PYTHONIOENCODING: "utf-8",
    },
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } },
    },
    {
      name: "mobile",
      use: { ...devices["iPhone 13"] },
    },
  ],
});
