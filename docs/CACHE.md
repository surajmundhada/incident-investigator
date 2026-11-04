# Optional Redis cache

Implemented 4 November 2026. PostgreSQL remains authoritative. Start with `scripts/start-stack.ps1 -LiveDemo -Knowledge -Agent -Cache`; omit `-Cache` for the default uncached deployment. The flag requires `-Knowledge`. Redis has no host port, no persistence, an internal Compose network, a 64 MB allkeys-lru limit and a 128 MB container limit. It is not a job broker or readiness dependency.

## What is cached

Only local embeddings and successful immutable runbook retrievals, including successful empty results. No logs, captures, generative responses, reports or investigation-owned evidence IDs enter these entries. API, worker and indexer construct independent pooled clients against the same cache. Direct KnowledgeStore construction, including the frozen evaluator, remains uncached unless explicitly given a client.

Embedding entries live for 30 days. Keys include format, application, locked model identity and exact-text SHA-256. Batch reads/writes deduplicate identical texts and restore input order. Model token limits still apply on hits. Values must contain finite, nonzero 384-dimensional vectors with matching scope. Passage and query embeddings both use this path.

Retrieval entries live for one hour. PostgreSQL resolves and validates the application revision and embedding identity on every call before Redis is consulted. Keys include resolved revision, application, service, environment, release, exact query, search mode, profile, model/reranker, limit and ranking/budget constants. A changed active revision naturally selects a new key. Old explicitly pinned revisions remain valid. Hits reconstruct the caller's query metadata, so an implicit revision/profile is not misrepresented as an explicit request.

Cache payload schemas forbid extra fields and validate applicability, citations and context bounds. Keys contain hashes, not plaintext queries. Hashing is not encryption: values include guidance and vectors. The local Redis network is a trusted application boundary; schema checks do not authenticate maliciously rewritten but structurally valid content. Redis must never be exposed publicly. Recognised-pattern redaction for uploaded documents happens before indexing; operator-managed files retain their original ingestion contract.

## Failure and concurrency

Clients use a pool of at most eight connections, 100 ms connect/socket timeouts, no automatic retries, and a process-local five-second bypass after a Redis error. Socket settings do not bound DNS: a real stopped-container check initially took four seconds. The final implementation bounds the caller's whole IO wait to 150 ms using an eight-worker executor with at most eight outstanding operations and no unbounded queue. Timed-out disposable reads/writes may finish in the background; this cannot advance investigation state. A repeat stopped-container check returned control in 151 ms and bypassed seven subsequent accesses. Misses, expiry, eviction, invalid payloads and unavailable Redis fall back to local inference/PostgreSQL. Failed cache serialization cannot discard a successful database result. Missing/wrong PostgreSQL knowledge still fails even if Redis has an entry. There is no stale-while-revalidate behavior. Scheduling/CPU pressure can add overhead; this is a bounded wait, not a hard real-time guarantee.

Sixty-four striped locks suppress duplicate retrieval work in one process. Waits are capped at 150 ms; a timeout may compute independently. Cross-process duplicate computation is accepted. Neither a distributed lock nor a cache write is required for correctness. Database/schema/user/server identity plus the explicit deployment namespace isolates development and test entries. Use a new namespace when changing deployment identity. The constructor does not ping Redis; a down cache cannot make application readiness fail.

## Measured result

The local experiment used the real locked CPU MiniLM encoder, PostgreSQL/pgvector and Redis, with thirteen documents/thirty-two passages and forty sequential trials per main workload. Every cached response was exactly compared with the uncached response. Full data is in cache-benchmark.json.

| Workload | Disabled p50/p95 ms | Embeddings only p50/p95 ms | Both layers p50/p95 ms |
| --- | --- | --- | --- |
| Four cold queries | 10.515 / 10.761 | 10.686 / 11.424 | 10.250 / 10.424 |
| Warm repeated queries | 9.245 / 9.979 | 4.684 / 5.260 | 1.694 / 1.998 |
| Unique queries | 9.781 / 11.680 | 10.617 / 12.339 | 12.466 / 27.082 |

Repeated-query median improved 81.7%, meeting the 20% experiment target. Forty full-cache hits avoided forty encoder inputs and forty ranking executions. Unique-query median increased about 27.4% with both layers; all forty queries missed and performed normal computation plus cache IO/validation. This is why caching stays optional. The measurements above were rerun after the whole-operation deadline/executor change. These are sequential, fixed-order measurements over a tiny authored corpus, not production/load/diagnosis-quality evidence. Cold percentiles over four samples are descriptive. No generative token savings or hosted calls were measured.

Reproduce after starting the cache stack and running `python scripts/verify_postgres.py` inside a one-off worker, with `AGENT_MODE=disabled`, an empty model key and `TEST_REDIS_URL=redis://redis:6379/0`. Then run `python scripts/benchmark_cache.py --trials 40` in that worker. The benchmark creates and removes its own random schema in investigator_test and deletes only its own cache keys. It does not read or alter frozen evaluation questions/results or production corpus heads. Never run FLUSHDB against shared Redis.

## Version and verification notes

Python client is pinned to redis-py 7.4.1; its wheel SHA-256 is `1fa4647af1c5e93a2c685aa248ee44cce092691146d41390518dabe9a99839b0`, verified against [PyPI's release files](https://pypi.org/project/redis/7.4.1/#files). Server is Redis 7.4.12-alpine, pinned by image digest in compose.cache.yaml. Pool/timeout/retry choices follow the supported [redis-py production controls](https://redis.io/docs/latest/develop/clients/redis-py/produsage/), with retries explicitly disabled for this disposable workload.

Tests exercise independent real clients, shared ingestion embeddings, complete retrieval hits, schema/namespace scope, revised heads and old citations, model mismatch, corruption, expiry, local concurrency, genuine Redis command rejection and a server absent at startup. Real service stop/restart confirmed fallback and loss/repopulation of disposable contents. A cache-enabled API/worker also started while Redis was down and completed an entire synthetic capture/runbook/report/local-archive workflow with zero model calls. See STATUS.md for the final regression and active deployment mode.

Interview explanation: PostgreSQL provides correctness; Redis buys repeated-work latency. We measured both the gain and miss overhead, versioned keys instead of deleting old corpus entries, and accepted duplicate computation to avoid turning cache coordination into a reliability dependency.

## Operator cache-status panel

Open http://127.0.0.1:5173/#cache. This read-only panel distinguishes unconfigured retrieval, cache off, configured caching and temporary error bypass. Enabled means configured, not independently verified Redis health. GET /api/diagnostics/cache reads in-memory telemetry only, sets Cache-Control: no-store, and never pings Redis. It exposes only whitelisted numeric counters, a random metrics-instance ID and timestamps; no URL, credentials, keys, queries or passage content.

The scope is one API process. Worker/indexer activity is excluded. Do not interpret these figures as application-wide cache hit rates, especially for investigations whose retrieval runs in the worker. Worker-heavy deployments require separate worker measurements before an app-wide activation decision. Embedding counters can include API-side document publication. Retrieval misses include absent/expired/invalid entries and unavailable cache reads. Error/bypass counters count IO operations, not failed investigations. One request can perform multiple operations.

Counters cover the current metrics instance. Export a JSON snapshot before restarting or changing modes; sampled_at/started_at/process_instance identify its observation period. S3's credential watcher recreates the API and therefore resets these process-local counters. No historical snapshots are stored automatically. Hit rates are null when no lookups exist rather than a misleading zero percent.

Search timing begins before scope/revision checks and includes successful retrieval, cache IO and fallback. The last 512 successful timings are retained separately for all/hit/miss-or-fallback/retrieval-cache-off paths. Failed searches are counted without entering success percentiles. Memory is bounded to four 512-sample deques, not an ever-growing request log. Empty samples display a dash. These figures exclude encoder startup, model calls and the remainder of an investigation. Comparing hits with misses from different requests is not a causal experiment. The older cache-benchmark.json predates this telemetry increment and remains historical; it was not rerun or rewritten.

### Choosing whether to enable Redis

Collect representative uncached traffic and export status; enable for a controlled trial with the same scope/query mix; compare p50/p95, errors and hit rates, alongside Redis resource usage measured separately. The panel does not collect server memory. Keep it enabled only if the observed benefit justifies its miss overhead and operational cost. There is no universal hit-rate threshold, automatic switch or browser Docker control. Exact query/scope matching means semantically similar wording is not automatically a hit. Low-traffic/tiny-corpus installations may reasonably leave caching off.

From the repository root, enable the complete local stack with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-stack.ps1 -LiveDemo -Knowledge -Agent -Artifacts -Cache
```

To disable it, rerun without -Cache, then stop the unused Redis service/container. This selects local archives. If using S3, first stop the previous foreground S3 watcher, change the local stack mode, then restore S3 with `.\.venv\Scripts\python.exe scripts/start_s3.py --cache --watch`. Omit --cache for cache-off. Keep only one watcher running: its later credential refresh otherwise restores its original API cache configuration. Reconfiguration is an operator action and may briefly interrupt the API; the investigator agent has no such control.

### Qualification of the panel

Tests cover scope/secret exclusion, no active probes, nullable empty rates, bounded thread-safe latency samples, unchanged search responses, disabled-mode measurements and real read-error bypass reporting. The live verification script scripts/verify_cache_status.py creates two disposable test containers, uses the existing reviewed corpus read-only, observes one real miss/one hit, stops only its own Redis, and verifies successful database/encoder fallback plus visible bypass. Its two containers are stopped even on failure. It never changes the main app's cache mode, submits incidents, invokes a model or accesses S3. The running local main app remains cache-off.
