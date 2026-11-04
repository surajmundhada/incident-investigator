// Read-only live review; no incident submissions, model calls or downloads.
import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const output = new URL("../../work/evaluation-preview/", import.meta.url);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: "msedge" });
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1100 },
  });
  const errors = [];
  let mutations = 0;
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (request.method() !== "GET") mutations++;
  });
  await page.goto("http://127.0.0.1:5173/#evaluation");
  await page.getByRole("heading", { name: "Evaluation results" }).waitFor();
  await page.screenshot({
    path: fileURLToPath(new URL("retrieval.png", output)),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Cache latency", exact: true })
    .click();
  await page.screenshot({
    path: fileURLToPath(new URL("cache.png", output)),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: fileURLToPath(new URL("mobile.png", output)),
    fullPage: true,
  });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > innerWidth,
  );
  const result = { errors, mutations, overflow, actual_model_calls: 0 };
  await writeFile(
    new URL("verification.json", output),
    JSON.stringify(result, null, 2),
  );
  if (errors.length || mutations || overflow)
    throw new Error("Live evaluation view check failed");
  console.log(JSON.stringify(result));
} finally {
  await browser.close();
}
