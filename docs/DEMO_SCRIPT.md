# Five-minute project demonstration

Use this as a reproducible placement demo, with the measured limits in STATUS.md.

## Start locally

From the repository root in PowerShell, start Docker Desktop, then:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-stack.ps1 -LiveDemo -Knowledge -Agent -Artifacts
powershell -ExecutionPolicy Bypass -File .\scripts\start-dashboard.ps1
```

The dashboard launcher occupies its terminal. Open http://127.0.0.1:5173 and API docs at http://127.0.0.1:8001/docs. The first command restores the local archive backend. Existing stored archives/reports are preserved.

For private S3, in another terminal after the local stack is ready:

```powershell
aws login --profile incident-investigator-setup
.\.venv\Scripts\python.exe .\scripts\start_s3.py --build --watch
```

Skip login while its session remains valid, and skip --build when the current S3 image is already built. The watcher must stay running; it is not a Windows service and does not survive reboot automatically. Only API/uploader are recreated for new one-hour sessions. Expect a brief API interruption during renewal. If refresh fails, the process exits and existing credentials expire; log in and rerun. Add --cache only if deliberately running the Redis-enabled stack. Starting start-stack.ps1 again restores local storage until start_s3.py is rerun.

## Show the product

1. Explain the user: a developer investigating a service failure from captured logs and team runbooks. Show Applications and the registered services/dependencies. These define the allowed investigation boundary.
2. Open a saved synthetic booking investigation. Walk through the input time window, evidence source/coverage, retrieved runbook citations and missing information. Explain that evidence-only reports make zero model calls and do not infer a root cause.
3. Open the historical Gemini shopping report, if present, and show its recorded model/tool usage. It localized checkout failures through payment; it did not prove the underlying cause. Do not present this as a newly executed demo or accuracy benchmark.
4. Show saved progress and a runbook citation. Explain immutable configuration/knowledge revisions and PostgreSQL leases/fencing: interrupted workers cannot overwrite newer owners.
5. On the synthetic report, select Archive investigation, wait for availability, and download. PostgreSQL tracks delivery; S3 stores immutable bytes; checksum verification and reconciliation cover interruption between those writes. Local archives remain visible but downloads are disabled while their backend is inactive.

Submitting a new investigation while AGENT_MODE=gemini can invoke the model. For a quota-free full onboarding demo, explicitly start the actual worker with AGENT_MODE=disabled before using verify_workspace.py; setting the verification client's environment alone does not disable that worker. See AGENT.md and APPLICATIONS.md rather than improvising configuration during an interview.

## Reproduce the cloud smoke

Use a saved, completed verification-* investigation with zero model calls:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_s3.py --investigation-id YOUR_SYNTHETIC_INVESTIGATION_ID
```

This requests an archive, waits for delivery, checks the regional signed download's SHA-256 and byte count, and checks duplicate-request identity. It can write one small synthetic object, at most 64 KB, and never deletes or invokes models. The verified 4 November example was 6,743 bytes. Signed URLs and credentials are not printed.

## Explain the engineering

- PostgreSQL owns transactional incident/job state; Redis is a disposable optional cache; S3 owns export bytes.
- Hybrid RAG combines filtered full-text and exact vector search. Baseline ranking remains default after mixed experimental evaluation.
- One bounded read-only agent keeps tool scope, budgets and stopping rules in application code.
- A saved checkpoint can be reused; an unknown model-call outcome is not automatically retried.
- SSE uses persisted event IDs and polling fallback. MCP exposes three existing read-only API operations.
- Migration 0008 corrected cross-backend object identity: the same key can exist independently in local storage and S3. The regression upgrades a populated database and preserves the old local archive.

Do not claim production readiness, universal incident support, diagnosis accuracy, full telemetry integration or public multi-user security. See INTERVIEW_GUIDE.md for tradeoffs and STATUS.md for exact verification.

## Recorded walkthrough and current qualification

README links a 20.72-second saved-workspace walkthrough (docs/assets/demo.webm). It shows overview, an explicitly historical saved AI report, applications, evaluation and cache status; it makes no new model call. The current model comparison is explicitly incomplete after provider errors, so do not describe the Evaluation page as a completed accuracy benchmark. Use RELEASE_READINESS.md for current gates and RESUME_BULLETS.md for defensible interview language.
