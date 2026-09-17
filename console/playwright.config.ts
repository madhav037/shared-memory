import { defineConfig } from "@playwright/test";

const consoleUrl = "http://127.0.0.1:4173";

// The journeys run against the built console and a real server, both started here.
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: { baseURL: consoleUrl, trace: "retain-on-failure" },
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  webServer: [
    {
      command: "uv run --project .. python e2e/serve.py",
      url: "http://127.0.0.1:8123/api/status",
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      stdout: "pipe",
    },
    {
      command: "npm run build && npm run preview",
      url: consoleUrl,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: { SHARED_MEMORY_SERVER: "http://127.0.0.1:8123" },
    },
  ],
});
