# Shopping service dependencies and boundaries

## Request flow

Checkout calls inventory availability first, then payment processing. Inventory success does not establish payment success. If inventory fails, checkout stops without calling payment. Use the dependency name as well as the response status to localize the failing boundary.

## Request correlation

Checkout propagates a valid request ID to inventory and payment. Compare records from the same request and incident window. A shared ID links observations but does not identify the underlying cause. Match service, timestamp, dependency, and status before correlating unrelated errors.

## Supported architecture

This release is an HTTP shopping simulation. It has no real payment gateway, order database, customer accounts, or stock reservation. Do not infer database connection exhaustion or external financial failures without an applicable architecture revision and actual observations. Process health is separate from successful business requests.

