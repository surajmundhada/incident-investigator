# Operational log adapter availability

## Adapter failure outcomes

source_timeout, source_unreachable, source_http_error, and invalid_source_response mean logs are unavailable. These adapter errors do not prove target application failure or target health. A successful empty query is a different outcome. Preserve the source error, query scope, and truncation status.

## Bounded evidence reads

The adapter permits a fixed configured source URL, a service allowlist, ordered incident windows no longer than an hour, at most 100 returned records, and a response-size cap. It does not accept arbitrary SQL, shell commands, or user-selected destinations.
