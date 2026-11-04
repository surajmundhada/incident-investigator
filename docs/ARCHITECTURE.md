# Implemented architecture

This is the local release architecture. The app is unauthenticated and must remain bound to loopback. Metrics/traces backends, Kubernetes, automatic remediation, public hosting and tenant isolation are outside this diagram. S3 is optional real cloud storage; the application itself runs locally.

## Components

```mermaid
flowchart TB
    UI[React dashboard on loopback] --> API[FastAPI on loopback]
    Alerts[Token-authenticated local alert ingress] --> API
    MCP[Read-only local stdio MCP] --> API
    API --> PG[(PostgreSQL state and pgvector)]
    PG --> Worker[Leased LangGraph worker]
    Worker --> Tools[Typed read-only tools]
    Worker --> Model[Opt-in Gemini HTTPS adapter]
    Tools --> Logs[Fixed log source or pinned captured logs]
    Tools --> RAG[Scoped runbook retrieval]
    RAG --> PG
    RAG -. optional .-> Redis[(Disposable Redis)]
    API --> Spool[Immutable local export spool]
    Uploader[Leased artifact uploader] --> Spool
    Uploader --> PG
    Uploader --> Objects[Local objects or private S3]
    API --> Objects
    PG --> Progress[Persisted events and reports]
    Progress --> API
```

The API, worker and uploader are separate processes sharing application modules. PostgreSQL owns admission, registry/snapshot revisions, jobs, leases, checkpoints, reports, events and artifact metadata. Redis is never authoritative. Provider credentials are supplied only to the model worker; AWS credentials only to the S3 API/uploader. This is credential placement, not complete compromise isolation: runtime database credentials and network reachability remain shared trust boundaries. Evaluation labels are excluded from application images.

## Incident admission, lease and fencing

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant PG as PostgreSQL
    participant W1 as Worker attempt A
    participant W2 as Worker attempt B
    Client->>API: Scoped incident and idempotency key
    API->>PG: Transaction: validate scope, insert incident and job
    PG-->>API: Commit or return prior matching admission
    API-->>Client: Accepted investigation ID
    W1->>PG: Claim ready job, lease token and attempt
    PG-->>W1: Owned claim with expiry
    W1->>PG: Save progress/checkpoint using token and valid lease
    Note over W1,PG: Tool reads may repeat after interruption
    Note over W1: Interruption and lease expiry
    W2->>PG: Claim expired job with a new token
    PG-->>W2: New owned claim
    W1->>PG: Attempt stale checkpoint or finalization
    PG-->>W1: Reject stale token or expired lease
    W2->>PG: Resume persisted state and finalize while owned
    PG-->>W2: Saved report and terminal events
    Client->>API: Replay persisted progress or fetch report
```

Admission and job insertion share one transaction; a reused key with different input is a conflict. Claims use database locking and token/expiry predicates on subsequent writes. This is at-least-once execution, not exactly-once execution. An unknown model-call outcome stops rather than repeating the external request. Saved call reservations/checkpoints make that ambiguity explicit. Cancellation invalidates ownership before further state transitions. LangGraph orchestration uses application-owned persisted state, not a native PostgreSQL LangGraph checkpointer.

## Retrieval and optional cache

```mermaid
flowchart TB
    Query[Query plus pinned application, service, environment and release] --> Head[Validate corpus revision and model identity in PostgreSQL]
    Head --> Enabled{Cache configured?}
    Enabled -->|No| Embed[Local query embedding]
    Enabled -->|Yes| Lookup[Versioned Redis retrieval lookup]
    Lookup -->|Valid hit| Result[Reconstruct bounded caller response]
    Lookup -->|Miss, invalid entry or outage| Embed
    Embed -. optional embedding lookup .-> ECache[(Redis embedding cache)]
    Embed --> FTS[PostgreSQL FTS candidates]
    Embed --> Vector[Exact pgvector cosine candidates]
    FTS --> RRF[Reciprocal rank fusion]
    Vector --> RRF
    RRF --> Bound[Apply context budget and immutable passage references]
    Bound --> Result
    Bound -. best-effort cache write .-> Lookup
```

FTS uses `plainto_tsquery` and `ts_rank_cd`, not BM25. Exact cosine search avoids approximate-index tuning for the current small corpus. Experimental query shaping, diversity and reranking remain explicit options; baseline ranking is retained. Cache keys include scope, revision, exact query and model/profile identity. Expiry, malformed data or Redis failure falls back to the database/encoder. Successful empty retrievals may be cached; unavailable retrievals are not successful empty results. Cache is optional and off by default. PostgreSQL validation still occurs on a cache hit.

## Export delivery and reconciliation

```mermaid
flowchart TB
    Request[Export a terminal investigation] --> Serialize[Canonical bounded JSON and SHA-256]
    Serialize --> Spool[Atomic local spool write]
    Spool --> Metadata[Admit artifact delivery metadata in PostgreSQL]
    Metadata --> Claim[Uploader claims lease and token]
    Claim --> Check{Object exists with matching size and checksum?}
    Check -->|Yes| Finalize[Lease-fenced available status]
    Check -->|No| Upload[Upload bytes with SHA-256 and encryption]
    Upload --> Verify[Verify stored size and checksum]
    Verify --> Finalize
    Upload --> Crash[Interruption before database commit]
    Crash --> Expire[Lease expires and later attempt claims]
    Expire --> Check
    Finalize --> Download[Verified local download or short-lived S3 redirect]
```

Object identity is deterministic per investigation, backend and content. Migration 0008 changed metadata uniqueness from object key alone to `(backend, object_key)`, allowing independent local and S3 copies. A later uploader can recognize an already successful object write. This reconciles two stores without asserting a distributed transaction. S3 downloads expire after 300 seconds; possession of the URL grants access during its validity. The unauthenticated local API is still a trusted local boundary. Checksum verification proves byte integrity, not privacy or semantic claim support.
