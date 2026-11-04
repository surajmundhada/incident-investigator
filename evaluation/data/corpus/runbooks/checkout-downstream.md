# Checkout downstream errors and bad gateway responses

## HTTP 502 from checkout

A checkout bad gateway response means a downstream call failed or could not complete. Inspect the ERROR record for its dependency field. Payment dependency and downstream status 503 support a failed payment boundary. Checkout status alone cannot distinguish payment from inventory failure or a network timeout.

## Follow the failing dependency

Use the checkout request ID and incident window to inspect the named dependency's logs. Compare its HTTP status with the caller's downstream error. Successful neighboring requests are counterevidence to a continuous outage. Missing downstream records may mean unavailable telemetry, transport failure, or a mismatched time window.

## Verification and limits

Read-only verification compares both sides of the request with the applicable service map. Do not restart services, change settings, or retry a real payment merely because a runbook suggests a hypothesis. Recovery after an operator action establishes observed recovery, not proof of the original cause.

