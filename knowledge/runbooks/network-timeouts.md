# Dependency timeouts and network reachability

## Response failure versus transport failure

A downstream request failed record with an HTTP status means an error response was received. A downstream request unavailable record without a status indicates a transport problem such as timeout, name resolution failure, or refused connection. This generic message does not distinguish those causes. Do not claim an unmeasured timeout duration.

## Bounded requests

Checkout configures a one-second HTTP client timeout for dependency calls and does not retry transactions automatically. Compare recorded duration, neighboring requests, and downstream logs. The configured timeout does not prove that every unavailable response was a timeout. Timeout categories apply to phases of the HTTP operation rather than guaranteeing a one-second total duration.

## Read-only follow-up

Compare dependency health, request errors, and available configuration evidence. A later successful response does not prove connectivity during the incident. Missing network observations should be listed as missing evidence rather than converted into a specific transport diagnosis.

