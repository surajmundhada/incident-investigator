# Synthetic captured-log example

These records are authored examples, not production telemetry and not a diagnosis benchmark. The placeholder credential is deliberately fake and demonstrates recognised-pattern redaction. There is no evidence here establishing the underlying cause of availability-api returning 503.

Register application.json under Applications, or use the fields in that file to fill in the registration form. Select the registered configuration and upload logs.jsonl. Review the suggested coverage bounds; coverage.json provides the wider declared interval used by the operator smoke script. Mark the upload as synthetic example data. notification-api is registered but is intentionally outside the declared evidence coverage. Its missing logs must not be interpreted as a healthy service.

Create an investigation for booking-api, select the saved snapshot, and describe the symptoms. The captured time window is historical and does not require fresh traffic. With the agent enabled this can use the configured hosted model; with the agent disabled it collects evidence and represents missing knowledge explicitly.

The operator smoke script registers and uploads these same files through the real API while checking that the current worker has its model disabled. No application-specific Python changes or additional target containers are needed.
