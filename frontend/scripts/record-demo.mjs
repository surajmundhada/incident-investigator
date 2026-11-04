// Read-only product walkthrough: saved reports, not a new model diagnosis.
import { chromium } from "playwright";
import { mkdir, copyFile, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const destination = new URL("../../docs/assets/", import.meta.url);
const temporary = new URL("../../work/demo-video/", import.meta.url);
await mkdir(destination, { recursive: true });
await mkdir(temporary, { recursive: true });
const historical = JSON.parse(
  await readFile(
    new URL("../../docs/example-agent-investigation.json", import.meta.url),
    "utf8",
  ),
);
const browser = await chromium.launch({ channel: "msedge" });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  recordVideo: {
    dir: fileURLToPath(temporary),
    size: { width: 1440, height: 1000 },
  },
});
const page = await context.newPage();
const video = page.video();
let mutations = 0;
page.on("request", (request) => {
  if (request.method() !== "GET") mutations++;
});
try {
  for (const [route, caption] of [
    ["", "Local incident workspace"],
    [historical.id, "Historical saved AI report — no new model call"],
    ["applications", "Versioned application and captured-log onboarding"],
    [
      "evaluation",
      "Measured results, including regressions and incomplete evaluation",
    ],
    ["cache", "Read-only cache operation and explicit measurement limits"],
  ]) {
    await page.goto(`http://127.0.0.1:5173/#${route}`);
    await page.getByText("API ready", { exact: false }).waitFor();
    await page.evaluate((text) => {
      const banner = document.createElement("div");
      banner.textContent = text;
      Object.assign(banner.style, {
        position: "fixed",
        bottom: "16px",
        right: "20px",
        background: "#163653",
        color: "white",
        padding: "12px 18px",
        borderRadius: "9px",
        zIndex: "9999",
        font: "14px system-ui",
      });
      document.body.appendChild(banner);
    }, caption);
    await page.waitForTimeout(1000);
    if (route === "")
      await page.screenshot({
        path: fileURLToPath(new URL("overview.png", destination)),
        fullPage: true,
      });
    await page.waitForTimeout(3000);
  }
  if (mutations)
    throw new Error("Demo recording unexpectedly issued a mutation request");
} finally {
  await context.close();
  await browser.close();
}
await copyFile(
  await video.path(),
  fileURLToPath(new URL("demo.webm", destination)),
);
console.log(
  JSON.stringify({
    recorded: true,
    mutations,
    new_model_calls: 0,
    path: "docs/assets/demo.webm",
  }),
);
