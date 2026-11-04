# Resume wording and interview defence

Use three bullets on a one-page resume. Describe this as a local portfolio application with a private S3 integration, not a public production platform. Measurements below are historical and scoped; STATUS.md records the current build and outstanding verification.

## Final Amazon SDE Intern version

**AI Incident Investigator | Personal Project**

Python, FastAPI, PostgreSQL/pgvector, LangGraph, Redis, AWS S3, Docker.

- Built a PostgreSQL-backed processing pipeline for AI incident investigation, atomically admitting incidents and jobs; implemented idempotency keys, worker leases and fencing tokens to deduplicate submissions and reject stale writes during recovery.
- Implemented a bounded LangGraph investigator with typed, read-only tools, enforcing application/service scope, observation windows and usage budgets; added report-reference validation and direct-citation HTTP-status consistency checks.
- Built hybrid full-text/vector retrieval with reciprocal rank fusion; reduced local repeated-query p50 from 9.2 to 1.7 ms, retaining optional caching after measuring a 27.4% unique-query latency regression.

Optional fourth bullet if this is the main project and space permits:

- Implemented private S3 exports with leased uploads, SHA-256 verification and interrupted-delivery reconciliation; fixed cross-backend object-key uniqueness during actual cloud integration.

For the performance bullet, the experiment used forty sequential measured requests per main workload/mode over thirteen documents/thirty-two passages. It is retrieval-only, not end-to-end AI speed. Keep the test count and migration number for the interview rather than crowding the bullets. “Personal Project” is enough in the heading; do not imply the application itself is hosted on AWS.

## Earlier general-purpose alternative

- Built an AI incident-investigation application using FastAPI, LangGraph and PostgreSQL/pgvector, combining scoped hybrid RAG with bounded read-only tools and evidence-linked reports.
- Implemented transactional job admission, idempotent requests, worker leases, stale-worker fencing and durable checkpoints to support recovery from interrupted investigations.
- Reduced median retrieval latency by 81.7% on a local repeated-query benchmark (9.245 to 1.694 ms), preserving results; retained optional Redis caching after measuring regression on unique queries.

Optional replacement if applying primarily to backend roles:

- Integrated private S3 archives with SHA-256 verification, temporary scoped IAM credentials, leased uploads and database/object reconciliation for interrupted delivery.

Suggested project title: **AI Incident Investigator — evidence-grounded service failure analysis**.

Stack: Python, FastAPI, LangGraph, Gemini, PostgreSQL, pgvector, Redis, S3, Docker Compose, React and TypeScript. Mention MCP only if prepared to explain the three read-only tools and local stdio integration.

## Explain it in 45 seconds

“A developer investigating a service failure often has to collect logs and search team runbooks manually. I built a workspace where they register the services, provide captured logs and guidance, and submit a bounded incident window. A read-only agent gathers scoped evidence and retrieves applicable runbooks, then produces a saved report with citations and missing information. I focused on reliability around the model: transactional admission, idempotency, leased workers, durable checkpoints and artifact reconciliation. I evaluated retrieval and caching rather than assuming extra components would help.”

## Defend each bullet

### What makes this more than a chatbot?

The application controls service scope, observation windows, allowed tools, input/output limits, job ownership and evidence persistence. The model chooses among declared functions; it cannot execute arbitrary code or repair systems. A report survives beyond a chat session, with pinned configuration/knowledge revisions and saved references.

### What exactly is hybrid RAG here?

Heading-aware, token-bounded Markdown passages are embedded locally with locked 384-dimensional MiniLM. PostgreSQL runs scoped full-text and exact cosine searches; reciprocal-rank fusion combines candidates. Application/service/environment/release filters and immutable corpus revisions constrain applicability. Returned passages include source lines and stable citations. PostgreSQL FTS is not BM25; there is no justified need for an approximate index with the current tiny corpus.

### Why PostgreSQL, Redis and S3?

PostgreSQL owns relational state and correctness: incident/job admission commits atomically, with evidence ownership and leases. pgvector also keeps the small retrieval index in the same system. Redis is optional/disposable repeated-work acceleration; failure falls back to the source. S3 stores immutable export bytes, while PostgreSQL tracks delivery state. Stable object keys, checksums and reconciliation handle the lack of a cross-store transaction.

### What happens if a worker crashes?

Its lease can expire and another worker can claim the job with a fresh fencing token. Only the current owner can save progress/finalize. Already-persisted observations/checkpoints can be reused. An external read may repeat; this is at-least-once execution, not exactly once. An unknown model-call outcome stops instead of automatically spending again.

### What does the 81.7% improvement actually mean?

It is the reduction in median hybrid retrieval latency on forty sequential measured repeated requests per mode, using the same local CPU encoder, PostgreSQL and corpus, with identical result comparison. It is not model latency, end-to-end investigation latency, production throughput or diagnosis accuracy. The corpus had thirteen documents/thirty-two passages. Unique-query median increased about 27.4%, so caching stayed optional. See CACHE.md and docs/cache-benchmark.json for all modes and tails.

We also measured p95: repeated-query p95 fell from 9.979 to 1.998 ms, while unique-query p95 increased from 11.680 to 27.082 ms. The statement in the pasted external feedback that no p95 existed was incorrect. There was no p99/confidence-interval analysis or concurrent cache comparison. The separate concurrency-four API read qualification is not a replacement for that missing cache experiment.

The strongest interview framing is the measured tradeoff and deployment decision, not the percentage alone. Explain the approximately 7.55 ms absolute median gain, exact repeated-query workload and unique-query regression.

### Did RAG improve accuracy to 90%?

No. Historical held-out section Recall@5 increased from 86.7% to 90.0% under an experimental ranking, while MRR@5 fell from 0.844 to 0.789. The change was not promoted. Recall is relevant-section coverage, not diagnosis accuracy. The later four-case generation pilot did not establish RAG superiority. Report any new workflow comparison separately, with its own dataset, denominator and failures; never merge these studies into one accuracy trend.

### Are citations proof the report is correct?

No. Code validates observation/passages belong to the investigation, and the new candidate adds a narrow direct-reference HTTP-status consistency check. Free-text causal claims and complete semantic support still require review. Earlier pilot review found partial per-claim support even when the cited IDs were valid; that finding is preserved.

### Why one agent? Why no Kubernetes?

One bounded explicit workflow is easier to inspect, budget and recover. Multiple agents need evidence of added value. Docker Compose fits the current single-machine application; no cluster-specific diagnosis or measured multi-node requirement justifies Kubernetes yet.

### What did you build and what was reused?

This is our application, inspired by Aurora/HolmesGPT, not a renamed fork. Libraries provide the web framework, workflow engine, storage clients and embeddings. Attribute external datasets separately and preserve their licenses. Independent public benchmark data is not the same as independent production-user validation.

## Evidence to keep ready

Have the dashboard and saved example open, plus the architecture diagram, STATUS.md, CACHE.md, EVALUATION_PROGRESS.md and the relevant study results. Show a captured-log report, a citation, persisted progress, archive delivery/download and the cache operator view. Be able to explain one real bug: global object-key uniqueness prevented local and S3 copies from coexisting; migration 0008 changed uniqueness to (backend, object_key), with a populated upgrade test and backup.

Do not claim production readiness, enterprise multi-tenancy, calibrated confidence, universal incident support, automatic remediation, comprehensive prompt-injection resistance, exactly-once execution, remote CI success or an external deployment unless separately verified.
