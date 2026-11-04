// Read-only visual check of the connected synthetic case created by verify_workspace.py.
import { chromium } from "playwright";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const result = JSON.parse(
  await readFile(
    new URL("../../work/workspace-verification.json", import.meta.url),
    "utf8",
  ),
);
const output = new URL("../../work/workspace-preview/", import.meta.url);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  channel: process.env.BROWSER_CHANNEL || "msedge",
});
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1050 },
  });
  const errors = [];
  let mutations = 0;
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (request.method() !== "GET") mutations++;
  });
  await page.goto(`http://127.0.0.1:5173/#${result.investigation_id}`);
  await page
    .getByRole("heading", { name: "Investigation summary", exact: true })
    .waitFor();
  await page.getByRole("link", { name: "Download archive" }).waitFor();
  await page.screenshot({
    path: fileURLToPath(new URL("report.png", output)),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: fileURLToPath(new URL("mobile-report.png", output)),
    fullPage: true,
  });
  let overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > innerWidth,
  );
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.goto("http://127.0.0.1:5173/#applications");
  await page
    .getByRole("button", { name: new RegExp(result.application) })
    .click();
  await page
    .getByRole("heading", { name: `Runbooks for ${result.application}` })
    .waitFor();
  await page
    .getByText("Current corpus: 1 document", { exact: false })
    .waitFor();
  await page.screenshot({
    path: fileURLToPath(new URL("applications.png", output)),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: fileURLToPath(new URL("mobile-applications.png", output)),
    fullPage: true,
  });
  overflow ||= await page.evaluate(
    () => document.documentElement.scrollWidth > innerWidth,
  );
  if (errors.length || mutations || overflow)
    throw new Error(JSON.stringify({ errors, mutations, overflow }));
  await writeFile(
    new URL("verification.json", output),
    JSON.stringify(
      {
        errors,
        mutations,
        overflow,
        source: "connected synthetic case, no new incident or model call",
      },
      null,
      2,
    ),
  );
  console.log(JSON.stringify({ errors, mutations, overflow }));
} finally {
  await browser.close();
}
