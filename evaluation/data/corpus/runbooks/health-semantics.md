# Process liveness versus business availability

## A reachable process can reject work

A successful health endpoint establishes that the service process responded. It does not establish that payment charge requests or inventory business requests succeeded. Compare business request status and correlated caller logs before claiming recovery or availability.

## Observed recovery

A later business request returning HTTP 200 demonstrates recovery for that request at that time. It does not prove service health during an earlier incident or reveal why the earlier request failed. Avoid extending one observation into a continuous availability claim.
