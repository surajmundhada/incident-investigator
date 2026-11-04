# Explain the implementation

Use code and measurements, not inflated claims. STATUS.md identifies the verified build; RAG_QUALITY_STUDY.md preserves historical evaluation. This is our implementation inspired by Aurora/HolmesGPT, with no copied source.

## Introduction

“I built an incident investigation workspace for small service applications. Developers register topology, supply captured logs and reviewed runbooks, then create incidents. A bounded agent gathers read-only evidence and retrieves applicable guidance. Reports cite saved records/passages and state missing evidence. I focused on durable jobs, recovery, scope isolation, retrieval evaluation and infrastructure failures.”

Evidence-only mode gathers records/guidance and makes no diagnosis. One historical live model smoke localized checkout's payment failure path; it did not establish the underlying cause or general accuracy.

## Design questions

| Question | Explanation |
| --- | --- |
| Why PostgreSQL instead of only a vector database? | Transactions and relationships support admission, idempotency, leases and evidence ownership. pgvector/full-text search also cover the small guidance corpus; JSON supports variable observations. |
| Why a database queue rather than Redis/Celery? | Incident/job commit atomically. SKIP LOCKED, leases and fencing avoid a broker/database dual write. Reconsider a broker for measured scheduling/throughput requirements. |
| Why Redis? | Avoid repeated encoder/ranking work. Final local repeated-query median fell from 9.245 to 1.694 ms; unique-query median became about 27.4% slower. Therefore it stays optional. |
| Can caching return another application's guidance? | Complete scope/version keys and payload validation isolate entries. PostgreSQL resolves revision/model identity before every lookup, even a hit. Old explicit revisions remain resolvable. |
| What happens during Redis failure? | A 150 ms whole-IO wait bound, no retries, five-second bypass and source fallback. A real Docker DNS delay escaped socket timeouts and motivated the capped executor. Full local investigation/archive worked with Redis stopped. |
| Why S3? | Immutable export bytes suit object storage; PostgreSQL retains queryable state/availability. Stable keys, checksums and reconciliation handle their non-atomic commits. A 6,743-byte synthetic private-S3 round trip passed; local and S3 copies coexist through backend-scoped keys. |
| Why one agent? | One explicit LangGraph loop is easier to budget/recover/inspect than multiple role agents. Code owns permissions and stopping limits. Additional agents require measured value. |
| Is this exactly once? | No. Execution is at least once. Tokens fence stale writers; saved observations/checkpoints are reused. An uncommitted external read may repeat. |
| What if a model request is interrupted? | Reserve usage first. An unknown outcome stops rather than automatically spending again; saved validated actions/results can resume. |
| Does LangGraph own persistence? | Application-owned lease-fenced rows persist graph state. Native PostgreSQL saver integration is not claimed. |
| Why SSE? | One-way progress suits EventSource. Saved IDs support replay; the UI deduplicates and drains terminal pages. JSON polling remains a fallback; the server still polls PostgreSQL internally. |
| Why MCP? | Expose selected existing read-only APIs to compatible local clients. It adds interoperability, not stronger reasoning or remediation. |
| Why not Kubernetes? | A local single-machine demo fits Compose. There is no cluster-specific or measured multi-node requirement yet. |

## Explain RAG

Markdown metadata carries application/service/global applicability, environment and release. Heading chunks preserve source lines/Markdown, stay within 180 embedding tokens and overlap twelve words. Locked local FastEmbed/ONNX MiniLM produces finite nonzero 384-dimensional vectors. Complete immutable revisions publish before their active pointer changes atomically.

Validate a query, resolve PostgreSQL revision/model identity, then consult the optional retrieval cache. A miss runs weighted English full-text and exact cosine search on filtered rows. Keep twenty candidates per channel, fuse ranks with k=60, then return at most six passages/1,200 context tokens. Distance <=0.75 is a heuristic, not confidence. PostgreSQL FTS is not BM25. Thirty-two reference passages do not justify an approximate vector index.

Baseline ranking remains default. Experimental query/diversity/reranking was not promoted after mixed internal outcomes. Do not select the favorable held-out metric after seeing results. Runbooks are guidance; logs are collected through typed tools instead of embedding every log line.

## Explain boundaries and recovery

Logs/runbooks are untrusted. Reviewed architecture context is separate. Code validates schemas, dependency scope, fixed windows, budgets and evidence ownership. Best-effort redaction does not prove every secret is removed. Valid citation IDs do not prove semantic claim support. User-declared capture coverage/checksums do not establish completeness or truth. Unavailable and successfully empty sources remain distinct.

Demonstrate an unchanged idempotent retry, cancellation, an old immutable citation, stale publication conflict, Redis outage and a pending-to-available archive. An uploader verifies an object already written before a crash, then finalizes with its current lease. Never assume missing DB success means a missing object. Missing spool bytes can be reconstructed only if they still match the original checksum.

Normalized alerts use stable occurrence IDs and closed observation windows. Duplicate deliveries reuse one incident; recurrences need new IDs. Resolved messages do not prove recovery or cancel a case. Native Alertmanager adaptation remains future work.

## Resume and evaluation honesty

The forty-question retrieval study and sixteen-call fixed-context answer comparison are small, internal and authored. Outcomes were mixed. Synthetic onboarding validates plumbing/provenance, not independent usefulness or diagnosis accuracy. Cache latency is a different experiment and does not establish better answers or hosted-token savings.

Suitable wording after checking STATUS.md: “Built a bounded incident investigation workspace with hybrid PostgreSQL/pgvector RAG, lease-fenced workers, versioned application onboarding and evidence-linked reports; tested recovery, cache outages and artifact reconciliation.” Include measured figures only with workload/scope. You can say “verified private S3 artifact upload and checksum-checked signed download,” scoped to the synthetic smoke case. Temporary credentials enter only API/uploader, with explicit renewal.

Remaining evidence: independently captured incidents, fresh bounded native-model/reference-support evaluation, sustained S3 credential-renewal/restart qualification, concurrent/resource measurements and clean-machine/remote-CI reproduction. Public authentication, full telemetry backends and multi-node hosting remain distinct future work.

Use DEMO_SCRIPT.md for the five-minute product walkthrough and safe startup commands.

## Measured improvement and the new pilot

Use the dashboard Evaluation tab and EVALUATION_PROGRESS.md. A supported performance claim is an 81.7% lower repeated-query retrieval median (9.245 to 1.694 ms) on the documented local 40-request workload, with identical results. Disclose that unique queries became 27.4% slower, so caching remains optional. Do not call this an AI accuracy improvement.

Historical experimental RAG recall rose 86.7% to 90.0% (+3.3 percentage points), but MRR fell 0.844 to 0.789. The ranking was not promoted. This is a tradeoff/rollout-decision story, not a deployed 90%-accuracy claim. The fresh four-case pilot has 4/4 logs-only, 3/4 full-context and 4/4 baseline-RAG structurally valid reports, twelve calls and 61,104 reported tokens. Same-assistant review found partial citation support; neither schema validity nor this tiny pilot establishes diagnosis quality. A semantic service-label rubric is needed before automatically scoring responsible-service accuracy. The sixteen held-out instances remain untouched.

## Explain optional-cache operation

The operator enables Redis through startup configuration after a matched-workload trial; incident users and the model do not switch it. The Cache status page shows actual API-process hit/miss counts, IO errors/bypass and bounded retrieval latency samples, even when Redis is off. Empty rates are unknown, not zero. Status polling never probes Redis and cached connections/queries are never exposed. Counters reset on process restart and can be exported before switching modes. Worker traffic needs separate measurements: this page is not global observability. A high hit rate alone does not prove a net speedup. See CACHE.md for the S3 watcher/configuration interaction.
