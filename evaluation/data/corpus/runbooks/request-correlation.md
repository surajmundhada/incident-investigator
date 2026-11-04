# Request ID correlation across HTTP services

## Joining observations

Use request_id to join checkout, inventory, and payment logs in the same observation window. Accepted IDs contain exactly 32 lowercase hexadecimal characters. Invalid supplied IDs are replaced at ingress. Timestamp proximity alone does not establish that two errors belong to the same request.

## Partial correlation

A matching request ID supports following a dependency boundary. A missing match can arise from log retention, an incorrect time window, a transport failure, or a request that never reached the downstream service. Preserve missing evidence; do not invent a trace or assume downstream success.
