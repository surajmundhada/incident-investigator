> Release-source note (5 November 2026): current report workflow remains bounded-investigator-v5; redaction is model-boundary-v3. Older versions/results below remain historical. Follow the root README for current setup.

# Resume checkpoint â€” 4 November 2026

Historical pause checkpoint. The user subsequently asked to resume; deployment and connected verification were completed during the resumed turn. STATUS.md and APPLICATIONS.md are authoritative for current state. The details below preserve what was known at the pause; they are not instructions to stop the resumed work. No autonomous goal was created.

## Work completed in the current increment

- Added catalog.py: bounded application/service/dependency schemas, deterministic configuration revisions, default shopping-demo configuration, pinned configuration resolution and direct-dependency permissions.
- Added registry.py and application revision/active-pointer tables. Registration appends immutable revisions and atomically changes the active scope pointer. Incidents pin application and configuration revision. Request hash version 3 preserves v1/v2 default-scope replay. Existing reports remain historical artifacts.
- Migration 0005 creates/seeds the registry, backfills legacy incident identity, and isolates knowledge by application. A separate application knowledge head, application-filtered candidates, explicit-revision checks and citation lookup prevent cross-application retrieval. Old demo citations remain accessible after migration.
- Generic service IDs replace hardcoded enums in admission, agent tools and retrieval. Known shopping architecture facts are limited to the exact built-in configuration. Workflow is bounded-investigator-v4; security version is model-boundary-v2. The default live adapter refuses other applications instead of reading demo logs.
- Migration 0006 adds immutable captured-log snapshots. Uploads are bounded to 1 MB JSON / 2,000 records / one-hour declared coverage. Known credential patterns are redacted before snapshot records are stored; original uploaded bytes are not retained. Source checksum, coverage, revision and synthetic-example provenance are retained. Snapshot queries preserve missing-coverage/unavailable semantics, cap results at 100 and never fall through to demo logs.
- Admission pins snapshot/configuration identities and rejects mismatched application, environment, release, service or coverage. Snapshot selection can pin a historical configuration even after a newer map is active.
- Worker routes captured investigations through EvidenceTools. Agent reference validation accepts owned snapshot logs. Evidence-only observations now use the dashboard's text/reference structure, and synthetic captures are labelled in report limitations.
- Added Applications.tsx (registration + JSONL upload), NewIncident.tsx (configuration/source selection, historical capture coverage, same-form retry identity), registry/snapshot types and navigation. The polished blue/white/pink theme is preserved.

## Verification at pause

- Earlier registry-only Docker run: 137 passed.
- Captured workflow Docker run before the final additional agent test: 147 passed.
- Host captured regression at that point: 132 passed, 15 PostgreSQL skips.
- Existing nine browser tests passed with registry/snapshot mocks. Two additional onboarding tests passed separately: register/upload/investigate a pinned capture, and mobile onboarding width. Browser tests use mocked API responses and no model calls.
- Final frontend production build and Prettier check passed.
- Final full Docker regression passed all 148 tests, including the scripted-agent snapshot citation test. The browser checks total eleven passing tests (nine existing plus two onboarding), run in separate batches with mocked APIs.

## Runtime boundary at the historical pause

The new source is NOT YET DEPLOYED to the main running stack. The isolated tests migrated owned test schemas only. The normal database/API/worker still need migrations 0005/0006 and rebuilt containers. Vite may hot-reload the new UI before those endpoints exist; do not interpret that as connected onboarding verification. Do not restart only the new worker image against the unmigrated normal database. Use the normal staged startup after reviewing the migration checkpoint.

No actual Gemini calls, billing changes, AWS provisioning, external messages, personal-file deletion, or Git commits were performed in this increment. Do not overwrite frozen RAG studies or call their historical results evidence for the changed prompt/corpus metadata.

## Resume steps

1. Read STATUS.md and this checkpoint, inspect the current diff/files and verify final recorded test results. No need to re-audit or rerun unchanged passing checks.
2. Review snapshot upload boundary and coverage behavior. In particular, enforce application/json on the manually streamed snapshot endpoint before treating it as ready for browser-facing use; it currently parses JSON irrespective of Content-Type. Add coverage for scope mutation and consider a PostgreSQL concurrent snapshot-upload check if needed.
3. Build and migrate the main stack, then verify registry/citation compatibility without model calls. Prepare a clearly labelled synthetic second-application example/configuration and a reproducible read-only or evidence-only smoke script. Do not submit a live investigation to an enabled model worker just to test plumbing: run the smoke with an explicitly disabled provider, then restore the prior configured mode.
4. Verify the real Applications UI, upload a snapshot, select its configuration/source and inspect the resulting captured report. Capture desktop/mobile screenshots and inspect them. Existing UI browser tests are mocked, so this connected check is still required.
5. Finish APPLICATIONS/captured-log documentation, API examples, README/ARCHITECTURE/DECISIONS/PLAN updates and current test counts. Explicitly distinguish user-declared coverage, synthetic examples, captured evidence, missing runbooks and actual-model execution.
6. Subsequent roadmap: genuine second-app evidence and usefulness evaluation, operator runbook onboarding, Redis with revision-aware keys/outage fallback, artifact consistency/S3 (credentials/provisioning remain separate), SSE, alerts and MCP. No automatic remediation or public hosting.

## Potential follow-up review points

- Application registry endpoints are local-workspace administration, not authenticated multi-tenancy. Application filtering is a data-scope boundary, not a tenant authorization claim.
- Incident configuration/snapshot pointers are validated by repository code; incident columns intentionally do not add foreign keys that require SQLite table recreation. Registry active heads and snapshot configuration rows do have foreign keys.
- Existing JSONL format requires 32-character lowercase-hex request IDs when supplied; users may omit that field. Broader correlation-ID formats are not implemented.
- Optional per-application runbook ingestion uses the operator manifest/CLI. There is not yet a public runbook upload UI or a published corpus for the second application; missing knowledge must remain explicit.

## Resumed completion

The follow-up review enforced JSON media type and pre-copy body bounds and added scope-mutation/concurrent-upload checks. Normal migrations 0005/0006 were applied after a local backup. Final regression passed 151 backend and eleven browser tests. Connected synthetic API and browser onboarding, old citations, and the original live failure/recovery path passed with zero new actual-model requests. The configured agent mode was restored afterward. Current operation and next priorities are recorded in STATUS.md; APPLICATIONS.md contains the user/API contract and reproduction steps. This historical pause checkpoint is resolved.
