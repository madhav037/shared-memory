import { defineConfig } from "@playwright/test";

// A port of the journeys' own. 4173 is where a developer's `npm run preview` listens, and that preview
// proxies to the Docker server on :8000, not to the seeded journey server below.
const consoleUrl = "http://127.0.0.1:4273";

// The journeys run against the built console and a real server, both started here.
export default defineConfig({
  testDir: "e2e",
  // One at a time: the journeys share one server and one fake GitHub, whose signed-in account is global.
  workers: 1,
  fullyParallel: false,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: { baseURL: consoleUrl, trace: "retain-on-failure" },
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  // Never reused: a server already answering is someone else's, holding whatever memory their last run left
  // behind, and attaching to it silently is how a green run stops meaning anything.
  webServer: [
    {
      command: "uv run python -m tests.console_e2e_server",
      cwd: "..",
      url: "http://127.0.0.1:8123/api/status",
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: "pipe",
    },
    {
      command: "npm run build && npm run preview -- --port 4273",
      url: consoleUrl,
      reuseExistingServer: false,
      timeout: 180_000,
      env: { SHARED_MEMORY_SERVER: "http://127.0.0.1:8123" },
    },
  ],
});
