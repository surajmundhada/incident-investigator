// Connected browser smoke. Requires the normal worker to be in evidence-only mode.
import { chromium } from "playwright";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

if (!process.argv.includes("--confirm-evidence-only")) {
  throw new Error(
    "Start the stack without -Agent, then pass --confirm-evidence-only. This script submits a synthetic investigation.",
  );
}
const root = new URL("../../", import.meta.url);
const sample = JSON.parse(
  await readFile(
    new URL("examples/booking-capture/application.json", root),
    "utf8",
  ),
);
const application = "booking-browser-example";
const output = new URL("work/onboarding-preview/", root);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  channel: process.env.BROWSER_CHANNEL || "msedge",
});
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1050 },
  });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto("http://127.0.0.1:5173/#applications");
  await page.getByText("API ready", { exact: false }).waitFor();
  await page.getByLabel("Application ID", { exact: true }).fill(application);
  const services = Object.entries(sample.services);
  for (let index = 0; index < services.length; index++) {
    if (index)
      await page
        .getByRole("button", { name: "+ Add service", exact: true })
        .click();
    await page
      .getByLabel(`Service ID ${index + 1}`, { exact: true })
      .fill(services[index][0]);
    await page
      .getByLabel(`Dependencies ${index + 1}`, { exact: true })
      .fill(services[index][1].dependencies.join(", "));
  }
  const registerResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/applications",
  );
  await page
    .getByRole("button", { name: "Register application", exact: true })
    .click();
  const registered = await (await registerResponse).json();
  await page
    .getByRole("heading", { name: `Evidence for ${application}`, exact: true })
    .waitFor();
  await page
    .getByLabel("JSONL file", { exact: true })
    .setInputFiles(
      fileURLToPath(new URL("examples/booking-capture/logs.jsonl", root)),
    );
  await page.getByLabel("These are synthetic example logs").check();
  const snapshotResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/snapshots",
  );
  await page
    .getByRole("button", { name: "Save evidence snapshot", exact: true })
    .click();
  const snapshot = await (await snapshotResponse).json();
  await page
    .getByRole("status")
    .filter({ hasText: "Snapshot saved" })
    .waitFor();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: fileURLToPath(new URL("applications.png", output)),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "+ New investigation", exact: true })
    .click();
  await page
    .getByLabel("Application configuration", { exact: true })
    .selectOption(registered.revision);
  await page
    .getByLabel("Evidence source", { exact: true })
    .selectOption(snapshot.id);
  await page
    .getByLabel("Incident title")
    .fill("Synthetic browser onboarding check");
  await page
    .getByLabel("Symptoms")
    .fill(
      "Collect these synthetic captured booking logs and show missing evidence explicitly.",
    );
  const incidentResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/incidents",
  );
  await page
    .getByRole("button", { name: "Investigate incident →", exact: true })
    .click();
  const admitted = await (await incidentResponse).json();
  await page
    .getByRole("heading", { name: "Investigation summary", exact: true })
    .waitFor({ timeout: 30000 });
  const response = await page.request.get(
    `http://127.0.0.1:5173/api/investigations/${admitted.investigation_id}`,
  );
  const saved = await response.json();
  if (
    saved.status !== "complete" ||
    saved.report.usage.model_calls !== 0 ||
    saved.incident.application !== application
  )
    throw new Error(
      "Expected a complete evidence-only investigation for the registered application",
    );
  if (JSON.stringify(saved).includes("example-token-not-real"))
    throw new Error("Known fake credential was not redacted");
  if (
    saved.report.conclusion !== "inconclusive" ||
    !saved.report.missing_evidence.some((value) =>
      value.toLowerCase().includes("runbook"),
    )
  )
    throw new Error(
      "Evidence-only reporting must expose missing guidance and uncertainty",
    );
  await page.screenshot({
    path: fileURLToPath(new URL("report.png", output)),
    fullPage: true,
  });
  await page.getByRole("button", { name: /^evidence \(/ }).click();
  await page.screenshot({
    path: fileURLToPath(new URL("evidence.png", output)),
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
  if (pageErrors.length || overflow)
    throw new Error(JSON.stringify({ pageErrors, overflow }));
  const result = {
    application,
    configuration_revision: registered.revision,
    snapshot_id: snapshot.id,
    investigation_id: saved.id,
    status: saved.status,
    model_calls: 0,
    synthetic_example: true,
    page_errors: pageErrors,
    mobile_document_overflow: overflow,
  };
  await writeFile(
    new URL("verification.json", output),
    JSON.stringify(result, null, 2) + "\n",
  );
  console.log(JSON.stringify(result));
} finally {
  await browser.close();
}
