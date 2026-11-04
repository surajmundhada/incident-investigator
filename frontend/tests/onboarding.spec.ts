import { expect, test, type Page } from "@playwright/test";

const demo = {
  application: "shopping-demo",
  environment: "local",
  release: "demo-v1",
  revision: "d".repeat(64),
  services: { checkout: { dependencies: [] } },
};
const revision = "e".repeat(64),
  snapshotId = "b".repeat(64),
  investigationId = "f".repeat(32);

async function workspace(page: Page) {
  const configurations: unknown[] = [demo];
  const snapshots: unknown[] = [];
  let registered: Record<string, unknown> | null = null,
    uploaded: Record<string, unknown> | null = null,
    admitted: Record<string, unknown> | null = null;
  await page.route("**/readyz", (route) =>
    route.fulfill({ json: { status: "ready" } }),
  );
  await page.route("**/api/**", (route) => {
    const request = route.request(),
      url = new URL(request.url());
    if (url.pathname === "/api/knowledge/head")
      return route.fulfill({ json: { revision: null, documents: [] } });
    if (url.pathname === "/api/applications") {
      if (request.method() === "POST") {
        registered = request.postDataJSON();
        const result = { ...registered, revision };
        configurations.push(result);
        return route.fulfill({ status: 201, json: result });
      }
      return route.fulfill({ json: { items: configurations } });
    }
    if (url.pathname === "/api/snapshots") {
      if (request.method() === "POST") {
        uploaded = request.postDataJSON();
        const body = uploaded!;
        const result = {
          ...body,
          id: snapshotId,
          record_count: (body.records as unknown[]).length,
          starts_at: Date.parse(body.starts_at as string) / 1000,
          ends_at: Date.parse(body.ends_at as string) / 1000,
          coverage_basis: "user_declared",
        };
        snapshots.push(result);
        return route.fulfill({ status: 201, json: result });
      }
      return route.fulfill({
        json: {
          items:
            url.searchParams.get("application") === "booking" ? snapshots : [],
        },
      });
    }
    if (url.pathname === "/api/incidents") {
      if (request.method() === "POST") {
        admitted = request.postDataJSON();
        return route.fulfill({
          status: 202,
          json: { investigation_id: investigationId },
        });
      }
      return route.fulfill({ json: { items: [] } });
    }
    if (url.pathname.endsWith("/events"))
      return route.fulfill({ json: { items: [] } });
    if (url.pathname === `/api/investigations/${investigationId}`)
      return route.fulfill({
        json: {
          id: investigationId,
          status: "complete",
          attempts: 1,
          incident: { ...admitted, starts_at: 1700000000, ends_at: 1700000010 },
          evidence: [],
          report: {
            mode: "evidence_collection_only",
            summary: "Collected captured log records.",
            observations: [],
            hypotheses: [],
            missing_evidence: [],
            suggested_checks: [],
            limitations: ["Scripted browser test."],
            usage: { model_calls: 0, tool_calls_started: 1, model_tokens: 0 },
          },
        },
      });
    return route.fulfill({ status: 404, json: { detail: "Not found" } });
  });
  return {
    registered: () => registered,
    uploaded: () => uploaded,
    admitted: () => admitted,
  };
}

test("publish reviewed Markdown only after explicit whole-corpus acknowledgement", async ({
  page,
}) => {
  await workspace(page);
  let publication: Record<string, unknown> | null = null;
  await page.route("**/api/knowledge/documents", (route) => {
    publication = route.request().postDataJSON();
    return route.fulfill({ status: 201, json: { revision, passages: 2 } });
  });
  await page.goto("/#applications");
  await page.getByRole("button", { name: /shopping-demo.*services/ }).click();
  await expect(
    page.getByRole("heading", { name: "Runbooks for shopping-demo" }),
  ).toBeVisible();
  await page.getByLabel("Complete Markdown corpus").setInputFiles({
    name: "checkout-guide.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# Checkout guide\n\nInspect downstream payment logs."),
  });
  const publish = page.getByRole("button", { name: "Publish runbooks" });
  await expect(publish).toBeDisabled();
  await page
    .getByRole("checkbox", {
      name: /Replace this application's entire active corpus/,
    })
    .check();
  await publish.click();
  await expect(page.getByRole("status")).toContainText(
    "Published 2 searchable passages",
  );
  expect(publication).toMatchObject({
    application: "shopping-demo",
    configuration_revision: demo.revision,
    expected_revision: null,
    replace_application_corpus: true,
    documents: [
      { id: "checkout-guide", service: "global", title: "Checkout guide" },
    ],
  });
});

test("register an application, upload JSONL and investigate its pinned capture", async ({
  page,
}) => {
  const state = await workspace(page);
  await page.goto("/#applications");
  await page.getByLabel("Application ID", { exact: true }).fill("booking");
  await page.getByLabel("Service ID 1", { exact: true }).fill("booking-api");
  await page
    .getByLabel("Dependencies 1", { exact: true })
    .fill("availability-api");
  await page.getByRole("button", { name: "+ Add service" }).click();
  await page
    .getByLabel("Service ID 2", { exact: true })
    .fill("availability-api");
  await page
    .getByRole("button", { name: "Register application", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Evidence for booking" }),
  ).toBeVisible();
  const records = [
    {
      timestamp: "2026-11-03T20:00:00Z",
      service: "booking-api",
      level: "ERROR",
      message: "Availability dependency returned an error",
      status_code: 502,
    },
    {
      timestamp: "2026-11-03T20:00:01Z",
      service: "availability-api",
      level: "ERROR",
      message: "Request failed",
      status_code: 503,
    },
  ];
  await page.getByLabel("JSONL file", { exact: true }).setInputFiles({
    name: "booking-example.jsonl",
    mimeType: "application/x-ndjson",
    buffer: Buffer.from(
      records.map((record) => JSON.stringify(record)).join("\n"),
    ),
  });
  await page.getByLabel("These are synthetic example logs").check();
  await page.getByRole("button", { name: "Save evidence snapshot" }).click();
  await expect(page.getByRole("status")).toContainText("Snapshot saved");
  await page.getByRole("button", { name: "+ New investigation" }).click();
  await page
    .getByLabel("Application configuration", { exact: true })
    .selectOption(revision);
  await page
    .getByLabel("Evidence source", { exact: true })
    .selectOption(snapshotId);
  await page.getByLabel("Incident title").fill("Booking requests failed");
  await page
    .getByLabel("Symptoms")
    .fill("Find the failed dependency in these captured logs.");
  await page.getByRole("button", { name: "Investigate incident →" }).click();
  await expect(
    page.getByRole("heading", { name: "Investigation summary" }),
  ).toBeVisible();
  expect(state.registered()?.application).toBe("booking");
  expect(state.uploaded()?.synthetic_example).toBe(true);
  expect(state.admitted()?.snapshot_id).toBe(snapshotId);
  expect(state.admitted()?.configuration_revision).toBe(revision);
  expect(state.admitted()?.starts_at).toBe(state.uploaded()?.starts_at);
  expect(state.admitted()?.service).toBe("booking-api");
});

test("application onboarding fits a narrow screen", async ({ page }) => {
  await workspace(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#applications");
  await expect(
    page.getByRole("heading", { name: "Bring your own context." }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
