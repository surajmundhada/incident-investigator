import { test, expect, type Page } from "@playwright/test";

const status = {
  enabled: false,
  state: "disabled",
  scope: "this API process only",
  started_at: 1700000000,
  process_instance: "test-instance",
  counters: { search_calls: 10 },
  hit_rates: { retrieval: null, embedding: null },
  latency: { uncached: { samples: 10, p50_ms: 9.78, p95_ms: 11.68 } },
  bypass_seconds_remaining: 0,
};
async function shell(page: Page) {
  await page.route("**/readyz", (route) =>
    route.fulfill({ json: { status: "ready" } }),
  );
  await page.route("**/api/incidents?*", (route) =>
    route.fulfill({ json: { items: [] } }),
  );
}

test("operator sees off state, uncached timings and explicit setup without mutations", async ({
  page,
}) => {
  await shell(page);
  const methods: string[] = [];
  page.on("request", (request) => methods.push(request.method()));
  await page.route("**/api/diagnostics/cache", (route) =>
    route.fulfill({ json: status }),
  );
  await page.goto("/#cache");
  await expect(
    page.getByRole("heading", { name: "Cache status", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Off", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(/Worker and indexer activity are excluded/),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "9.78 ms", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("cell", { name: "No lookups yet" })).toHaveCount(
    2,
  );
  await page
    .getByText("Operator setup and S3 precautions", { exact: true })
    .click();
  await expect(page.getByText(/Keep only one watcher running/)).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(methods.every((method) => method === "GET")).toBe(true);
});

test("bypass is visible and an API failure clears stale status", async ({
  page,
}) => {
  await shell(page);
  let unavailable = false;
  await page.route("**/api/diagnostics/cache", (route) =>
    route.fulfill(
      unavailable
        ? { status: 503, json: { detail: "Unavailable" } }
        : {
            json: {
              ...status,
              enabled: true,
              state: "bypassing",
              counters: {
                retrieval_hits: 7,
                retrieval_misses: 3,
                errors: 1,
                bypass: 2,
              },
              hit_rates: { retrieval: 0.7, embedding: null },
              bypass_seconds_remaining: 4,
            },
          },
    ),
  );
  await page.goto("/#cache");
  await expect(
    page.getByRole("heading", { name: "Temporarily bypassed" }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "70.0%", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/Cache I\/O errors: 1/)).toBeVisible();
  unavailable = true;
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Cache status is unavailable",
  );
  await expect(
    page.getByRole("heading", { name: "Temporarily bypassed" }),
  ).toHaveCount(0);
});
