import { defineConfig, devices } from "@playwright/test";

// End-to-end config. Runs against the Vite dev server (the demo episode
// auto-loads, so no backend is required). Chromium is launched with software
// WebGL (SwiftShader) so it works headless without a GPU.
//
//   npx playwright install chromium   # one-time browser download
//   npm run e2e                       # starts vite + runs the specs
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    actionTimeout: 10_000,
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
