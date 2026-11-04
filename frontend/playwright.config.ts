import { defineConfig } from "@playwright/test";

const testPort = Number(process.env.TEST_DASHBOARD_PORT || 5173);
const testUrl = `http://127.0.0.1:${testPort}`;

export default defineConfig({
  testDir: "./tests",
  outputDir: "../work/dashboard-tests",
  workers: 1,
  use: {
    baseURL: testUrl,
    headless: true,
    channel: process.env.BROWSER_CHANNEL || undefined,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${testPort}`,
    url: testUrl,
    reuseExistingServer: !process.env.CI,
  },
});
