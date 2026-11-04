> Current release setup: use the root README quickstart, which generates local credentials, applies migrations and documents all prerequisites. Historical setup milestones below are preserved; proposed components and earlier dependency counts are not current release claims.

# Setup and first slice

## What works now

The first slice accepts an incident, atomically persists its investigation and job, collects logs through a read-only HTTP adapter, stores evidence, and produces a clearly labeled evidence report. It implements idempotency keys, bounded input, leases, stale-worker rejection, limited abandoned-job recovery, and ordered pollable progress.

The base slice requires no model key. Local runbook retrieval uses -Knowledge; see docs/RETRIEVAL.md. The opt-in LangGraph/Gemini worker now uses -Agent and explicit private Free-tier configuration; see docs/AGENT.md. Redis, S3, alert webhooks, SSE, and React remain pending. FastAPI's API explorer is the current interface.

The next increment now supports actual HTTP checkout/payment/inventory services and live logs. Start with scripts/start-stack.ps1 -LiveDemo and follow docs/LIVE_DEMO.md. The default startup below still selects fictional evidence.

## Prerequisites

- Python 3.12 or 3.13. Development was verified on Windows Python 3.13.1; the container targets Python 3.12.
- Docker Desktop with Linux containers and its WSL 2 backend for the PostgreSQL path. It has now been installed and verified.
- Node is not required until frontend work begins.

PostgreSQL is the durable application database. Docker runs it and the API/worker in separate containers. PostgreSQL does not need a separate Windows installation when using Compose.

## Python environment

Run from the repository root in PowerShell. The initial implementation already created .venv and installed the lock file's dependencies in this workspace.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
```

requirements.lock pins the versions used for the initial verification. pyproject.toml declares permitted dependency ranges; update the lock deliberately when dependencies change.

## Inspect without Docker

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-preview.ps1
```

Open http://127.0.0.1:8000/docs. The launcher runs database migrations, one worker, and a fictional HTTP evidence source. The preview uses SQLite only because it is explicitly requested by this launcher. It never silently substitutes SQLite when PostgreSQL is unavailable.

Keep the launcher terminal open while using these links. A passing preview test starts and then stops its own temporary server; it does not leave a server running for your browser. If the browser reports that the site cannot be reached, start the launcher and confirm that it prints the preview address without an error. The automated assistant may also start a background preview; its PID and logs are recorded under the ignored work directory. No frontend website exists yet: /docs is the API explorer.

In another terminal, create a sample incident:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\create-sample-incident.ps1
```

The script prints the URL for the investigation. Wait briefly, then open that URL to inspect the persisted evidence and report. The incident's time window must include preview startup; restart the preview if it has been running for more than ten minutes before using the sample script.

Both the startup message and evidence report identify fixture data. These messages are authored examples, not actual failures, live operational evidence, or evaluation results. No root cause is inferred by this version.

Press Ctrl+C in the preview terminal to stop it. Its database remains under the ignored data directory for later inspection.

## PostgreSQL container path

Verified on Docker Engine 29.9.2 (Linux), Compose 5.6.1, PostgreSQL 17.11, and Python 3.12 containers.

```powershell
.\.venv\Scripts\python.exe .\scripts\init_local_env.py
powershell -ExecutionPolicy Bypass -File .\scripts\start-stack.ps1
```

The initializer creates an ignored .env with a generated local database password; it never overwrites an existing file or prints the password. The launcher finds Docker at its per-user or all-users installation path and makes its credential helper available in the launcher process without changing system PATH.

This starts PostgreSQL, applies migrations in a one-shot service, and starts API, worker, and the fictional evidence source in the background. Open http://127.0.0.1:8001/docs. Port 8000 remains available for the optional SQLite preview. Database ports are not published. Override API_PORT in .env if needed.

Create a sample incident:

```powershell
.\scripts\create-sample-incident.ps1 -BaseUrl http://127.0.0.1:8001
```

Use a URL-safe local password for the example connection URI, or supply a properly encoded DATABASE_URL when adapting the deployment. The Compose image tags are initial compatibility targets, not immutable digest locks; image qualification remains pending.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-agent.lock
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend demo-app tests scripts
.\.venv\Scripts\python.exe -m ruff format --check backend demo-app tests scripts
```

PostgreSQL tests are skipped in host-only runs unless TEST_POSTGRES_URL is configured. For the running local stack, the verification runner creates a separate investigator_test database and runs the suite. Each PostgreSQL test uses and cleans up a random schema inside that test database. Application records are not reused or dropped. Run only against this local development stack.

If Docker is on PATH after opening a new terminal:

```powershell
Get-Content .\scripts\verify_postgres.py -Raw | docker compose -f compose.yaml -f compose.demo.yaml -f compose.knowledge.yaml -f compose.agent.yaml exec -T worker python -
```

If Docker is not on PATH, use the executable path discovered by scripts/start-stack.ps1. Verified milestones passed 37, 43, 57, then 88 tests without skips in Docker. Twelve checks now require PostgreSQL/pgvector. Full tests need requirements-agent.lock and can be streamed into the agent worker container instead of the smaller API image. CI installs that lock; remote CI has not run.

Windows sandboxed environments may restrict the local socket pair used by FastAPI's test client. The initial checks passed when permitted to use local sockets outside that sandbox. A Starlette/httpx deprecation warning is currently known; it does not fail the tests.

## API examples

POST /api/incidents requires Idempotency-Key and title/service/description/starts_at/ends_at. Services must belong to the selected registered configuration; the built-in application uses checkout/payment/inventory. Times must include a timezone, be ordered and cover at most one hour. Other applications select their scoped configuration/captured source as described in APPLICATIONS.md.

Submitting the same key and equivalent input returns the same investigation. Changing the input while reusing the key returns HTTP 409. A new key creates a new incident; semantic duplicate detection is not implemented.

GET /api/investigations/{id}/events?after={event_id} returns ordered JSON events. The dashboard now uses the additional /events/stream SSE transport for running cases, retaining JSON fallback and terminal page draining. See PROGRESS_STREAM.md.

## Current boundaries

Reusable application onboarding, Markdown publication, optional Redis, progress streaming, normalized alerts and local artifacts are implemented. The normal schema is now 0007. See STATUS.md for the latest verified counts/mode, RUNBOOK_UPLOADS.md for publication and CACHE.md for measured performance. Start with -LiveDemo -Knowledge -Agent -Artifacts for the local archive; add -Cache only when desired. Restore the configured agent mode after quota-free checks. No AWS resources are required for this local command.

The React dashboard is available on http://127.0.0.1:5173 with `powershell -ExecutionPolicy Bypass -File scripts/start-dashboard.ps1`; keep the API running on port 8001. See DASHBOARD.md for dependencies, browser checks, polling behavior and retry semantics. Final security/dashboard regression passed 122 Docker tests including thirteen PostgreSQL checks; the frontend passed seven scripted browser checks and separate read-only connected verification. See SECURITY.md for the scope of prompt-injection controls.

- SQLite-only checks do not establish PostgreSQL locking behavior. Six separate PostgreSQL checks now verify migrations, concurrent claims, idempotency, stale-owner rejection, and evidence preservation in the local container setup.
- Committed results and application-owned agent state are reused on worker recovery. Native LangGraph PostgreSQL saver integration is not implemented.
- Tool availability is recorded; automatic external-query retries and circuit breakers are deferred.
- API binds localhost in the preview. No authentication or public hosting is provided.
- Cancellation and explicit artifact-delivery retry are implemented. Investigation retry, original-document archival and live S3 qualification remain separate work; actual-model behavior is documented in AGENT.md.
