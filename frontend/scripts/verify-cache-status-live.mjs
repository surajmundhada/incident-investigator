// Read-only connected UI check. Does not probe Redis or submit investigations.
import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const output = new URL("../../work/cache-status-preview/", import.meta.url);
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
  await page.goto("http://127.0.0.1:5173/#cache");
  await page.getByRole("heading", { name: "Off", exact: true }).waitFor();
  await page.screenshot({
    path: fileURLToPath(new URL("desktop.png", output)),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByText("Operator setup and S3 precautions", { exact: true })
    .click();
  await page.screenshot({
    path: fileURLToPath(new URL("mobile.png", output)),
    fullPage: true,
  });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > innerWidth,
  );
  const result = {
    errors,
    mutations,
    overflow,
    observed_mode: "off",
    actual_model_calls: 0,
  };
  await writeFile(
    new URL("verification.json", output),
    JSON.stringify(result, null, 2),
  );
  if (errors.length || mutations || overflow)
    throw new Error("Live cache-status view check failed");
  console.log(JSON.stringify(result));
} finally {
  await browser.close();
}
