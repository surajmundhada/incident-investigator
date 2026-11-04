# Missing logs and insufficient evidence

## Empty results versus unavailable sources

A successful query with zero matching records differs from a timeout, unreadable log file, or unavailable service telemetry. Empty results cover only the requested service, time window, and retained data. An unavailable source provides no evidence that requests were healthy.

## Retention and truncated evidence

Local logs rotate and queries return a bounded number of records. Truncated responses may omit relevant errors; older coverage after rotation cannot be guaranteed. Preserve truncation and the query window. Do not describe retained records as a complete incident history.

## Abstain when support is missing

Separate observed facts from possible explanations. A runbook provides general guidance, not a current incident observation. If no available observation distinguishes competing causes, mark the cause inconclusive and suggest permitted read-only checks. A retrieval score is not a calibrated probability.

