# Live application demonstration

## Purpose and boundary

This increment replaces authored example logs with operational evidence from three running HTTP services. Checkout calls inventory, then payment. It is a deliberately small shopping simulation: there is no real payment processor, customer data, reservation system, or order database. The failures and network requests are real executions of this application, under operator-controlled conditions. This is not a diagnosis benchmark or proof of AI accuracy.

The investigator still collects evidence only. It does not use an LLM, retrieve documents, or automatically follow dependencies yet. The demonstration therefore creates separate checkout and payment investigations and checks their shared request ID. Cross-service investigation will be added with the agent tools.

## Start and verify

From the repository root in PowerShell, with Docker Desktop running:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-stack.ps1 -LiveDemo
.\.venv\Scripts\python.exe .\scripts\verify_live_demo.py
```

The launcher uses compose.yaml plus compose.demo.yaml. API_PORT still defaults to 8001; if changed, pass --api with the correct URL to the verification script. The default launcher without -LiveDemo selects the old fixture source instead. An old fixture container may remain running after switching; the live worker uses demo-evidence, not that container.

| Address | Purpose |
| --- | --- |
| http://127.0.0.1:8001/docs | Investigator API explorer |
| http://127.0.0.1:8002/docs | Checkout API explorer |
| http://127.0.0.1:8002/metrics | Checkout request/error counters and duration sum/count |
| http://127.0.0.1:8003/docs | Operator-only fault controls |

The verification script restores payment to healthy in a finally block, checks healthy checkout, sets payment unavailable for at most 60 seconds, verifies a real 502 checkout response, submits investigations over that window, and checks persisted live records containing checkout 502 and payment 503 with the same request ID. It then resets payment and checks recovery. Run one operator experiment at a time: this local controller is not a concurrent experiment scheduler. The current demonstration is a smoke check, not a load test.

## Inspect manually

1. Open checkout's API explorer. POST /checkout with {"item":"book","quantity":1}; expect 200.
2. Open the operator explorer. POST /faults/payment with {"mode":"unavailable","ttl_seconds":60}.
3. Repeat checkout; expect 502 and a request ID. Inventory succeeds and payment responds 503.
4. Create an investigator incident scoped to checkout and the UTC failure window, using a new Idempotency-Key. Repeat for payment if inspecting both sides manually.
5. GET each investigation. Evidence should show data_origin=live, relevant statuses, and matching request_id fields. Reports remain evidence_collection_only with zero model calls.
6. Reset with {"mode":"healthy"}, or wait for the fault's TTL to expire. Repeat checkout; expect 200.

## Design decisions

- Reuse the existing Python dependencies and image for a small laptop-friendly increment. The services run as separate processes/containers; sharing code does not replace the actual HTTP boundaries.
- Keep business behavior small. A target database is deferred until a database-failure scenario needs one. The eventual target database must be separate from the investigator database.
- Generate a bounded 32-character request ID at ingress and propagate it to downstream requests and structured logs. This is request correlation, not OpenTelemetry distributed tracing.
- Use a fixed one-second downstream HTTP timeout, no redirects, and no automatic transaction retries. Checkout stops after a failed dependency. Readiness of the process is separate from successful payment behavior.
- Use rotating JSONL logs, about 2 MB active plus one backup per service. The evidence source mounts logs read-only and filters by allowlisted service and bounded time window. It returns at most 100 records and reports truncation conservatively after rotation. This is a small local adapter, not Loki or complete historical retention. Concurrent rollover or a partially read line can produce an explicit unavailable response; snapshot consistency is not guaranteed.
- Expose simple Prometheus-format counters and duration sum/count. Metrics reset on process restart; no Prometheus collector, metric tool, histogram, or tracing backend is connected yet.
- Keep the fault controller on a separate Docker network. It writes temporary settings to a volume mounted read-only by payment. Neither the worker nor evidence source receives that volume. The worker shares an observation network with the read-only evidence source, and has no shared network with targets or the controller.
- Controller modes and expiry values stay out of application responses and logs. The observable symptom does not establish why payment became unavailable. Knowing the injected fault is the operator's ground truth, not agent evidence.

The controller is unauthenticated and published on localhost for this local demonstration. Docker/host administrators can inspect all containers; this separation applies to the investigator's configured runtime interfaces and is not a sandbox against a malicious host administrator. Do not expose these services publicly.

## Verification and limits

The first run passed all 43 tests inside the Python 3.12 Docker image, including six PostgreSQL integration tests. Added coverage checks controller validation/reset/expiry, checkout HTTP-error and timeout handling, request-ID propagation, counters, real-log filtering, source corruption, truncation, and persistence through the investigator worker. Windows host tests passed 37 checks with six PostgreSQL checks skipped when no test URL was configured.

The real-container script independently verified healthy traffic, a downstream failure, two persisted investigations with live correlated evidence, and recovery. These checks do not measure diagnosis accuracy, performance under load, concurrent operator changes, or behavior of a real external payment provider.

The running-worker isolation check passed: the evidence source was reachable while target service and controller connections failed. Docker mount inspection confirmed read-only logs in the evidence source, read-only control settings in payment, and no control mount in the worker.

To verify network isolation inside the running worker (using the full Docker executable path if needed):

```powershell
Get-Content .\scripts\verify_demo_isolation.py -Raw | docker compose -f compose.yaml -f compose.demo.yaml exec -T worker python -
```

Next: add reviewed runbooks, retrieval, and a bounded model-backed workflow that can follow the observed payment dependency. Keep fault labels and control access outside that workflow.

## Additional recorded scenarios (4 November 2026)

The isolated payment controller now accepts healthy, unavailable, slow and application_error, all with the existing 5–300 second TTL. Slow adds a fixed 1.5-second handler delay, exceeding checkout's real one-second HTTP deadline. Checkout records a 504 and an explicit downstream deadline event; the payment may later complete 200. Application_error produces a payment 500 and an operational handler-error event; checkout propagates 502. These are controlled synthetic fault injections, not independent real production failures. No database-failure label is claimed: the demo payment handler has no business database.

The read-only investigator source exposes timestamps, durations, statuses and request correlation, never controller mode/TTL/ground-truth labels. Checkout now distinguishes timeouts (504) from other unavailable/failed downstream requests (502). The old unavailable scenario remains checkout 502/payment 503. The operator-only capture script always resets healthy, records all three services before any agent query, refuses overwriting an output directory and rejects truncated capture coverage.

Actual capture command: `.\.venv\Scripts\python.exe scripts/capture_demo_cases.py --output evaluation/diagnosis-v2/captures --repeats 6`. Do not rerun into that frozen directory. Twenty-four windows were recorded successfully (eight development, sixteen held-out), with synthetic provenance and SHA-256 input/split locks. Variants differ in traffic count and timing; fault families are shared, so repeated windows are not independent root-cause categories. Labels remain under evaluation, excluded by .dockerignore. The separate protocol/pilot compares model outputs; the capture success itself is not diagnosis accuracy.
