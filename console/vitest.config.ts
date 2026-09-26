import { defineConfig } from "vitest/config";

// The console's own units only. The browser journeys in e2e/ are Playwright's, and end in .ts just the same.
export default defineConfig({
  test: { include: ["src/**/*.test.ts"] },
});
