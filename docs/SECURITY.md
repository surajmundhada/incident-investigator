# Security boundaries and self-review

This is an unauthenticated local portfolio workspace. Do not expose API, dashboard, demo controls, PostgreSQL, Redis or Docker to a network. The author/AI-assisted review is a self-review, not an independent audit or penetration test. Source tests verify selected boundaries, not comprehensive attack resistance.

## Evidence and privacy

Incident descriptions, logs and retrieved passages are untrusted evidence. Prompts distinguish these from application-owned reviewed topology, while typed tools enforce allowed service/dependency scope, observation window and bounded arguments. The model has no arbitrary shell, SQL, path or URL tool and cannot remediate a service.

Current source uses model-boundary-v3. It redacts recognized credential patterns and AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN and ALERT_WEBHOOK_TOKEN aliases in string assignments and nested dictionaries, including supported case/separator variants. The provider additionally removes exact occurrences of its configured key. JSON is copied without changing observation indices/reference IDs. Pattern matching does not detect every secret, encoding or personal datum.

Original incident text and live/legacy evidence may remain in local database records, API responses and exports despite outbound model redaction. New snapshot/runbook uploads perform recognized-pattern redaction before storage/indexing, but that is not encryption or a comprehensive privacy filter. Older captures and frozen evaluation records are not rewritten. Review every export before sharing; checksum verification does not sanitize content. Never include local databases, volumes, .env, work/ or data/ in a public release.

## Access and network controls

- All published Compose ports bind 127.0.0.1; frontend development/preview binds loopback. A regression test checks these source contracts.
- General API routes have no login, per-user authorization or tenant isolation. Application scoping is an evidence boundary, not an authenticated tenant boundary.
- Alertmanager and normalized webhooks require a configured token of at least 32 characters, compare it with hmac.compare_digest, and bound headers/body size. Blank configuration disables ingress. Native diagnostic URLs are ignored.
- Log reads use the operator's fixed source, disabled redirects/environment proxies and bounded response size. Application/tool schemas accept no fetch URL. Local stdio MCP restricts its API host and exposes selected read-only operations.
- The provider uses a fixed HTTPS origin. Provider traces are disabled. Unknown model-request outcomes stop rather than retrying.
- SQL values are bound parameters. Retrieval's interpolated identifiers/functions are code-owned choices.
- Runbook uploads generate validated filenames; corpus/artifact paths enforce resolved-root containment. React renders text rather than executing raw HTML/Markdown or loading generated remote links/images.
- S3 downloads use a 300-second signed URL and no-store redirects. Anyone holding that URL may use it until expiry. The local download endpoint remains unauthenticated.

## Configuration and credentials

DATABASE_URL must be explicit for host processes; there is no database password fallback. scripts/init_local_env.py generates a local password without overwriting an existing .env. Compose supplies the full internal URL. Public IAM examples use ${ARTIFACT_S3_BUCKET}; the actual bucket/region remain operator configuration. AWS scoped temporary credentials go only to S3 API/uploader, not the model worker. Gemini credentials go only to the worker. Docker administrators can inspect process/container environments; do not expose the engine.

## Known limitations

Runtime containers currently retain their default user and share database credentials; separate least-privilege runtime/migration database roles are not implemented. Per-job budgets do not cap aggregate submissions or account billing. Remaining typed-JSON routes do not all have a pre-parse streamed body cap. Shared local networks, volumes and database roles are trusted; credential placement alone does not contain a compromised process. Comprehensive semantic claim validation, independent usefulness review, container-OS scanning and independent security review remain outside these checks.

Historical tests/studies refer to their recorded versions. The release redaction changes were not used to rerun or relabel model studies. Refer to STATUS.md and release verification records for tests actually executed, including skips and failures.
