# Local alert admission

POST `/api/webhooks/alerts` accepts a provider-neutral normalized delivery, not the native Alertmanager webhook format. The separately bounded native version-4 adapter is now implemented below. Keep a stable closed observation window and occurrence ID when retrying; create a new occurrence ID for a later recurrence. The service does not invent a changing end time that would break idempotency or silently collect evidence outside the declared interval.

Enable explicitly with an ignored environment variable ALERT_WEBHOOK_TOKEN of at least 32 characters, passed only to the API by Compose. Send Authorization: Bearer followed by that token. No token is generated or logged automatically. The endpoint is disabled without configuration. The rest of the local UI/API remains unauthenticated; this is not public deployment security.

```json
{
  "source": "local-monitor",
  "occurrence_id": "payment-errors-20261104T060000Z",
  "status": "firing",
  "incident": {
    "application": "shopping-demo",
    "service": "checkout",
    "environment": "local",
    "release": "demo-v1",
    "title": "Checkout dependency failures",
    "description": "Monitor observed checkout errors in this completed window.",
    "starts_at": "2026-11-04T05:55:00Z",
    "ends_at": "2026-11-04T06:00:00Z"
  }
}
```

The 16 KB JSON body uses the existing incident contract: registered application/service, timezone-aware ordered window of at most one hour, optional pinned configuration/captured source. Unknown fields are rejected without echoing the body. Source, occurrence ID and application produce a hashed alert idempotency key. Atomic incident/job admission and duplicate races use the existing PostgreSQL mechanism. Exact retries return the same investigation; changing input for the same occurrence returns 409. Resolved deliveries are acknowledged without creating or cancelling an investigation. They do not prove a service recovered.

This can admit a model-backed investigation when the worker has AGENT_MODE enabled. Deterministic tests use no provider. The original normalized endpoint remains a single-delivery interface. The native adapter below supports batches; no alert-server deployment, external monitor subscription, rate-limiting infrastructure or automatic remediation is installed.

## Native Alertmanager version-4 adapter

POST /api/webhooks/alertmanager accepts the standard version-4 envelope described by [Prometheus webhook configuration](https://prometheus.io/docs/alerting/latest/configuration/#webhook_config). It uses exactly the same configured bearer token and JSON-only streaming checks as the normalized endpoint. The complete body is capped at 64 KB, at most twenty alerts; truncatedAlerts must be zero so truncated delivery is not silently accepted. Native diagnostic URLs, fingerprint and additive metadata are ignored and never fetched. This is an adapter qualification, not a deployed Alertmanager server/subscription.

Every firing alert must have per-alert labels application, service, environment, release and investigator_source. Required annotations investigator_window_start and investigator_window_end declare the fixed closed investigation window; summary/description are optional. Optional investigator_configuration_revision and investigator_snapshot_id pin registered captured evidence. See the existing incident contract for time, scope and identifier limits. These are integration-specific fields inside the standard native envelope, so an existing unconfigured alert rule is not automatically usable. The source must freeze them per occurrence: a moving now()-derived annotation would conflict on retry. Do not use endsAt to invent a moving observation interval; native firing delivery can change that field between notifications.

Occurrence identity hashes receiver, sorted per-alert labels and normalized startsAt; the source/application are also included by the existing admission key. The same alert recurring with a new startsAt creates another investigation. Changed annotation/input for the same identity conflicts rather than overwriting the original evidence scope. Resolved entries are acknowledged without creating or cancelling an investigation. They do not establish recovery.

Payload shape and normalization are validated for the full batch before admission. Registered-scope checks and database commits then happen independently per alert. Response atomicity is per_alert and each item reports accepted/ignored/rejected/conflict, its index and the saved identity when admitted. Successful entries remain committed if another entry is rejected. HTTP 409 signals a conflict, otherwise 422 signals an invalid registered scope; a valid batch returns 202. Exact batch retry reuses successful jobs. This avoids claiming a cross-batch transaction or silently swallowing partial admission. The remainder of the local UI/API is still unauthenticated; do not publish it as a secure multi-user service.

Tests cover token/disabled mode, native metadata changes, duplicate/recurrence/resolved behavior, count/body/truncation bounds, whole-shape validation before side effects, generic validation errors that do not echo annotations, and explicit partial-batch retry/conflict behavior.
