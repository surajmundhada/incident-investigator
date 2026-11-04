# Optional private S3 connection

The application runs locally. S3 is optional real AWS storage, not application hosting. The quickstart uses no AWS account and the ordinary -Artifacts override selects local storage. Configure ARTIFACT_S3_BUCKET and AWS_REGION privately for your own existing dedicated bucket; no real bucket/account identifiers belong in source.

## IAM template and temporary credentials

infra/iam/incident-archive-policy.json is a template containing ${ARTIFACT_S3_BUCKET}, not an immediately attachable account-specific policy. Render the placeholder with your private configuration before reviewing/applying it. The local launcher uses rendered_archive_policy(bucket) to derive the expected policy and checks the actual role permissions against it. Only lowercase DNS-label bucket names with letters/digits/hyphens are supported by this operator bridge.

The policy permits GetObject/PutObject under exports/v1/* and read-only privacy/region checks. ListBucket on a dedicated bucket is deliberate: a missing HeadObject can return 403 without it. Do not convert genuine access denial into a successful miss. ListBucket reveals object names across that dedicated bucket; do not reuse the example unreviewed on a bucket containing unrelated metadata. There is no DeleteObject, bucket creation, ACL mutation or account administration in this application policy. Requests require HTTPS.

The optional launcher expects a reviewed archive role named IncidentInvestigatorArchiveRole and an IncidentInvestigatorArchiveAccess managed policy in the authenticated account, trusting only the resolved human setup role. It checks trust, policies, session duration, privacy, ownership, encryption and region before assuming the role. This repository never provisions them automatically.

After separate AWS CLI browser login and explicit bucket/role setup, run from a configured local virtual environment:

```powershell
aws login --profile incident-investigator-setup
.venv/Scripts/python.exe scripts/start_s3.py --build --watch
```

The launcher reads configured bucket/region from environment or ignored local .env. It supplies only temporary scoped credentials to API/uploader; the model worker receives none. Human credential caches are not mounted into containers. No credential values or signed download URLs are printed. Docker administrators can nevertheless inspect container environment values.

The foreground watcher recreates API/uploader before session expiry and may briefly interrupt the API. It is not an installed service. One earlier timed renewal succeeded and a later earlier-version CLI renewal failed. The revised watcher has bounded transient-only retries, exclusive locking and an expiry guard, but a sustained full timed cycle of that revised implementation remains unobserved. Stop/restart explicitly after code/configuration changes; release verification never restarts an existing watch process.

## Historical bounded external check

Before public-source sanitization, one existing synthetic zero-model report completed private S3 upload, regional signed download, checksum/size verification and duplicate identity replay. The recorded report was 6,743 bytes. This is one bounded historical check, not a sustained service or independent user test. Operator evidence is in ignored work/s3-roundtrip-verification.json and is deliberately excluded from public source. The public repository therefore does not include independently reproducible raw cloud-check evidence; the statement is an operator-recorded checkpoint.

Migration 0008 changed artifact uniqueness to (backend, object_key), preserving separate local/S3 copies; its populated migration and downgrade behavior are tested. Download links expire after 300 seconds. scripts/verify_s3.py derives its expected destination from ARTIFACT_S3_BUCKET and AWS_REGION rather than a hardcoded operator bucket. Running that optional script uploads a small existing synthetic report and needs explicit operator authorization; release tests use SDK contract doubles and never call AWS.

Original incident/live evidence may remain in exports. A private bucket, short-lived URL and matching checksum do not make content safe to publish. Review content before any sharing.
