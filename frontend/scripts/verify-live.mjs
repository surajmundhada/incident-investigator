// Read-only verification against the local API. Never submits an investigation.
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";

await mkdir("../work/dashboard-preview", { recursive: true });
const browser = await chromium.launch({
  channel: process.env.BROWSER_CHANNEL || "msedge",
});
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("http://127.0.0.1:5173/");
  await page.getByText("API ready", { exact: false }).waitFor();
  const response = await page.request.get(
    "http://127.0.0.1:5173/api/incidents?limit=100",
  );
  if (!response.ok())
    throw new Error("Live API unavailable through dashboard proxy");
  const { items } = await response.json();
  const completed = items.find((item) => item.status === "complete");
  if (completed) {
    await page.goto(`http://127.0.0.1:5173/#${completed.investigation_id}`);
    await page.locator(".detail h1").waitFor();
    await page.screenshot({
      path: "../work/dashboard-preview/report.png",
      fullPage: true,
    });
    await page.getByRole("button", { name: /^evidence \(/ }).click();
    await page.screenshot({
      path: "../work/dashboard-preview/evidence.png",
      fullPage: true,
    });
  }
  if (errors.length) throw new Error(errors.join("\n"));
  console.log(
    JSON.stringify({
      api_ready: true,
      incidents: items.length,
      inspected_completed_investigation: completed?.investigation_id || null,
      page_errors: errors,
      submitted_incidents: 0,
    }),
  );
} finally {
  await browser.close();
}
