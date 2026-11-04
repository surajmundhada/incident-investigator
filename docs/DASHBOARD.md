# Local investigation dashboard

The React/TypeScript dashboard uses Vite with a same-origin development proxy to the existing FastAPI API on 127.0.0.1:8001. It binds to 127.0.0.1:5173. No credentials are built into the browser bundle. Package versions and transitive dependencies are locked in frontend/package-lock.json. Styling is local CSS with no CDN, external fonts or UI library.

## Start

The reliability increment adds guarded Markdown publication on Applications, SSE progress with JSON fallback, and a terminal-case archive panel. Start with the optional -Artifacts flag for the working local archive, without AWS. See RUNBOOK_UPLOADS.md, PROGRESS_STREAM.md and ARTIFACTS.md for current contracts; older polling descriptions below document the retained fallback.

First start Docker Desktop and the API/worker:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-stack.ps1 -LiveDemo -Knowledge -Agent
```

Then, in a second terminal:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-dashboard.ps1
```

Open http://127.0.0.1:5173. The launcher installs missing frontend dependencies with a project-local cache under work/npm-cache. Node 20.19+ or a supported newer version is needed. API ready means the API/database readiness check succeeds; it does not establish worker or provider health. With the agent enabled, submitting an investigation can consume configured provider quota. Viewing existing reports does not generate model calls.

## Implemented behavior

- Overview showing counts for the latest 100 loaded incidents, in-progress and completed jobs. Counts are not diagnosis accuracy or system health metrics. The API-ready indicator checks API/database readiness only.
- Recent-case table, status tabs, text search and an all-investigations view with ten rows per page. Filters/pagination apply to the loaded latest 100, not a server-wide archive. Persistent navigation and five recent shortcuts replace the original full incident-list sidebar. Select an investigation with a bookmarkable URL hash; #investigations opens the all-cases view.
- Register an application/service map and upload bounded JSONL evidence under Applications. See APPLICATIONS.md for schema, coverage and provenance limits.
- Submit an incident against a registered configuration and captured snapshot, or the built-in live shopping source. Captures pin their historical coverage window/configuration; live demo windows look back 5/15/30/60 minutes. An unchanged retry reuses both idempotency key and exact request body/window within the open form. Closing/reloading discards this retry state; cross-reload deduplication is not claimed.
- Inspect status, scope, saved observations/hypotheses, missing evidence, suggested checks, model usage, provenance and limitations.
- Follow report log references to evidence cards and highlighted record indices. Resolve immutable runbook passages through the citation API. All text is rendered inertly, without raw HTML or external generated links.
- Inspect ordered persisted events and collected evidence, cancel a queued/running investigation, and export the stored investigation as JSON.
- Explicit API errors and empty/partial states. A complete database job is displayed independently from an inconclusive/partial generated report.

The list refreshes every five seconds and active detail/events every 1.5 seconds. Requests do not overlap within each poll loop; changing selection aborts old requests. Event IDs are deduplicated, pages are drained after terminal completion, and terminal investigations stop polling. This is polling, not SSE. SSE/reconnect support remains a later increment. There is no fault-control button in this dashboard.

Exports and stored evidence views can contain original local evidence; model-boundary redaction does not sanitise these exports. This dashboard is not a public deployment. Docker packaging, authenticated access and full accessibility review remain pending.

## Checks

```powershell
Set-Location frontend
npm --cache ../work/npm-cache ci
npm --cache ../work/npm-cache run build
```

Browser tests use a mocked API and make no live model requests:

```powershell
# Windows: reuse installed Edge rather than downloading a browser.
$env:BROWSER_CHANNEL = 'msedge'
# If C: has little space, point temporary browser files to E:.
$env:TEMP = 'E:\incident-investigator\work\browser-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
node node_modules/@playwright/test/cli.js test
```

Eleven browser checks cover safe text/citation rendering, failed-submit idempotency, cancellation, event pagination, API outage, mobile report layout, JSON download, overview counts/filter/navigation, internal table scrolling, application registration/capture submission and mobile onboarding. A separate connected browser smoke verifies real local onboarding with the model disabled; see APPLICATIONS.md. Remote CI has not been run.

With the actual backend running, `node scripts/verify-live.mjs` verifies readiness through the proxy and opens an existing completed investigation. It writes screenshots under work/dashboard-preview and creates no incidents. Scripted browser screenshots are named scripted-* to distinguish them from live data. After recovering Docker from a full C: disk, this connected check passed: eight existing incidents, saved Gemini report/evidence rendered, zero browser page errors and no incident submissions. These historical reports are not new model executions with the updated security prompt.
