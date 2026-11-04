# Register applications and investigate captured logs

Implemented and connected locally on 4 November 2026. A developer can register a service map and supply incident logs without modifying investigator Python code. The original shopping demo remains available as the built-in live source. Other applications currently use uploaded captures, not automatically discovered cloud/HTTP connections.

## Browser workflow

1. Open http://127.0.0.1:5173/#applications. Register an application ID, environment, release and service map. IDs use lowercase letters, digits and hyphens; each dependency must reference another service in this same map. Registration creates a configuration revision; it does not connect live logs.
2. Select the registered configuration and upload a JSONL file. Review the suggested start/end bounds and explicitly select which services the export covers. Mark authored/example data as synthetic. Save the evidence snapshot.
3. Choose New investigation, select the application configuration and saved snapshot, then choose an affected service and describe the symptoms. Captured investigations use the snapshot's declared historical window rather than a fresh look-back window.
4. Inspect observations, references, unavailable sources and limitations in the saved report. With the model disabled, this is evidence collection only; with the configured agent enabled, the agent can request permitted follow-up evidence. A completed job can still have an inconclusive conclusion.

The checked-in examples/booking-capture directory contains an explicitly synthetic three-service configuration and four log records. These are not production telemetry or an accuracy benchmark. The fake credential tests recognised-pattern redaction. notification-api is registered but has no declared capture coverage.

## Configuration and permission boundaries

```json
{
  "application": "booking-example",
  "environment": "local",
  "release": "v1",
  "services": {
    "booking-api": {"dependencies": ["availability-api", "notification-api"]},
    "availability-api": {"dependencies": []},
    "notification-api": {"dependencies": []}
  }
}
```

At most twenty services and ten direct dependencies per service are accepted. Duplicate IDs, self-dependencies, unknown dependencies and unknown fields are rejected; global is reserved as a runbook applicability tag. Configuration contains no arbitrary URLs, shell commands or free-text instructions to elevate into the system prompt.

Revisions hash canonical configuration, including application/environment/release and sorted dependency lists. PostgreSQL stores immutable revisions and an active pointer per scope. Registration of identical configuration reuses its revision; publishing a changed map does not change already-admitted investigations. The root service and its direct dependencies define the current tool scope. Reading a downstream service's dependency map does not expand that permission boundary transitively.

Incident admission resolves and pins the configuration. A selected capture pins its original configuration even if a newer map is active; the UI can fetch the historical revision. New idempotency identities include application, requested configuration and snapshot identity. Original v1/v2 default-demo keys remain replayable. Active-pointer publication and incident admission are transactional, and old revision rows remain available.

## Supported JSONL records

Each nonblank line is a JSON object:

```json
{"timestamp":"2026-11-03T18:00:12Z","service":"booking-api","level":"ERROR","message":"Downstream request failed","request_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","dependency":"availability-api","status_code":503}
```

Required fields: timezone-aware timestamp, registered service ID, level (INFO/WARNING/ERROR), and message (1–2,000 characters). Optional fields: request_id (32 lowercase hexadecimal characters), registered dependency, status_code (100–599), and finite nonnegative duration_ms. Additional fields are rejected; normalise other exporters to this documented schema or omit unsupported optional fields. This is not an arbitrary plain-text log parser. Broader request-ID formats remain future work.

The browser accepts up to 750 KB of JSONL. It parses the file and sends structured JSON to POST /api/snapshots. The server requires application/json (optionally with a charset), stops buffering beyond 1,000,000 bytes, and permits at most 2,000 records and one hour of declared coverage. These are ingestion limits, not a hardened public upload service or a load qualification.

## Coverage, provenance and redaction

- Coverage is the uploader's declaration, not verified completeness. Suggested bounds derived from record timestamps must be reviewed. Records outside the declared bounds/services are rejected. A service with no declared coverage returns unavailable, not a successful empty result.
- An incident must fit the capture's application, environment, release, configuration, declared time window and affected-service coverage. Agent follow-up queries keep that scope. The adapter returns at most 100 matching records in original order, marks truncation, and retains citation indices within the persisted result.
- A capture never falls back to demo logs. Another application, even with a service called payment, cannot use the built-in shopping log adapter.
- Recognised credential patterns are redacted before snapshot records and source labels are stored. Original uploaded bytes are not archived. The source checksum hashes the parsed canonical upload payload, not the raw JSONL bytes; snapshot identity also includes the redaction version. Unknown secrets, encodings and personal information may still be present. Review inputs yourself.
- Identical parsed uploads/metadata reuse a snapshot; duplicate concurrent publication is tested in PostgreSQL. There are no update/delete endpoints for revision or snapshot bodies. A checksum establishes identity, not truthfulness or origin authenticity.
- Captured means supplied as a snapshot, not independently verified production telemetry. Synthetic examples have an explicit flag propagated into evidence/report limitations. Raw legacy live-log records are unaffected by this upload-specific redaction and remain local.

## Runbooks and application isolation

Each runbook manifest belongs to one application. Add application, environment, release and service applicability to each document; use service global for shared guidance within that application only. The operator CLI remains the ingestion path; there is not yet a runbook-upload UI.

Knowledge has independent active revisions per application. Keyword/vector candidates, pinned revision resolution and citation lookup are application-filtered. Runbook citation URLs include the application. An application without a published corpus receives an explicit unavailable result; it does not inherit shopping-demo guidance. The first successful knowledge revision/ranking profile remains pinned across agent follow-up searches.

The corpus is separate from the service configuration: a configuration pin is not a guarantee that every same-release runbook procedure is applicable. Source review and evidence/claim support remain necessary. Changes to application metadata create a new corpus revision; historical benchmark files and old citations are retained.

## API surface

| Endpoint | Behavior |
| --- | --- |
| GET /api/applications | Active configurations by application/environment/release |
| POST /api/applications | Validate/publish a configuration; return revision and reuse status |
| GET /api/applications/revisions/{revision} | Resolve an immutable historical configuration |
| GET /api/snapshots?application={id} | Latest 100 snapshot metadata records for that application |
| POST /api/snapshots | Bounded JSON capture ingestion; return immutable snapshot metadata |
| POST /api/incidents | Existing endpoint plus application, optional configuration_revision and snapshot_id |
| GET /api/knowledge/passages/{id}?application={id} | Application-scoped immutable passage lookup |

Full body schemas are in http://127.0.0.1:8001/docs. The registry and list filters are local workspace administration/data scoping, not authenticated multi-tenancy. The API remains localhost-only; no public registration/hosting is implemented.

## Reproduce the quota-free smoke

Start Docker and the stack WITHOUT the agent override:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-stack.ps1 -LiveDemo -Knowledge
```

From a shell with Docker on PATH (or use the executable resolved by start-stack.ps1):

```powershell
docker compose -f compose.yaml -f compose.demo.yaml -f compose.knowledge.yaml exec -T worker python scripts/verify_captured_workflow.py
```

This runs inside the evidence-only worker, registers booking-example, uploads the synthetic files through the real API, verifies upload/admission deduplication, collects three booking records, verifies recognised fake-credential redaction, confirms missing knowledge and asserts zero model calls. Repeated identical API smoke requests reuse their admission key/window; they do not rewrite historical reports.

For connected browser verification, keep that evidence-only stack running, then from frontend:

```powershell
$env:BROWSER_CHANNEL = 'msedge'
node scripts/verify-onboarding-live.mjs --confirm-evidence-only
```

The script uses the actual UI/API, registers booking-browser-example, uploads JSONL, creates an evidence-only investigation and checks desktop/mobile rendering. It submits a new synthetic case each run. Screenshots/verification metadata go under ignored work/onboarding-preview. Do not run it against a model-enabled worker: the flag is an operator assertion, not remote worker attestation.

After quota-free checks, restore the usual configured agent stack with scripts/start-stack.ps1 -LiveDemo -Knowledge -Agent. This enables future user-submitted model investigations but does not itself generate a new model request.

Verification for this increment: 151 backend tests passed in Docker including sixteen PostgreSQL checks; eleven mocked browser tests passed; production build and formatting passed. Connected API/browser captured flows, original live failure/recovery and old RAG citation compatibility were verified. New captured checks used zero actual-model calls; scripted-agent tests establish tool/reference mechanics, not native-model diagnosis accuracy, prompt-injection resistance or independent user benefit.
