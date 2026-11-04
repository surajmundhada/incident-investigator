# Versioned runbook retrieval

## Implemented boundary

The current reviewed corpus has thirteen documents and thirty-two passages; the original seven-document/twenty-passage version is frozen separately. PostgreSQL stores immutable revisions, passage text, source/checksum/line metadata, full-text indexes, and vectors. The opt-in agent can generate reports using this guidance; see AGENT.md. RAG_QUALITY_STUDY.md documents the subsequent experiments and rollout hold.

Runbooks live in knowledge/runbooks, with an explicit manifest in knowledge/manifest.json. Do not ingest project plans, test labels, fault settings, controller documentation, or arbitrary workspace files. These guides describe observable symptoms and competing explanations, without access to experimental ground truth.

## Reproduce locally

Registered applications can now publish bounded reviewed Markdown from the dashboard/API using an expected revision and explicit whole-application replacement; see RUNBOOK_UPLOADS.md. Optional Redis reuses local embeddings and successful immutable retrieval results, with PostgreSQL checks on every query; see CACHE.md for actual measurements and outage behavior. The operator manifest path below remains available for multi-scope corpora and the reviewed shopping reference set.

From the project root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-retrieval.lock
.\.venv\Scripts\python.exe scripts/prepare_embeddings.py
powershell -ExecutionPolicy Bypass -File scripts/start-stack.ps1 -LiveDemo -Knowledge
.\.venv\Scripts\python.exe scripts/verify_knowledge.py --output work/retrieval-development.json
.\.venv\Scripts\python.exe scripts/verify_live_demo.py --require-knowledge
```

The embedding preparation is an explicit public model download, about 90 MB for the weights. It verifies checksums from knowledge/embedding-lock.json. Runtime does not download a model or contact a hosted embedding API. Do not use --write-lock for routine setup: it is for deliberately recording initial artifact hashes when reviewing a model update. Weights remain under ignored data/embeddings/minilm and are mounted read-only.

The optional Compose override builds CPU embedding dependencies only into the investigator API, worker, and indexing job. Target services keep the base image. API and worker have 768 MiB memory caps in this mode; this is a configured limit, not a load/resource qualification. Dependencies are cached separately from source code in Docker build stages.

The indexing service runs after migrations and publishes before the API/worker start. Re-running startup reuses an existing identical revision; it currently recomputes embeddings before checking for that revision. An embedding cache is deferred to Redis work. Use the existing fixture startup without -Knowledge to keep the dependency-light preview.

## Inspect the API

Open http://127.0.0.1:8001/docs and POST /api/knowledge/search:

```json
{
  "query": "payment 503",
  "service": "payment",
  "environment": "local",
  "release": "demo-v1",
  "mode": "hybrid",
  "limit": 3
}
```

The response includes the corpus revision, embedding identity, retrieval configuration, candidate counts, passage content, service applicability, source file, document checksum, heading, source line numbers, and citation URLs. GET /api/knowledge/passages/{id} resolves the immutable stored passage, including after a new corpus becomes active. It does not read whichever source file happens to exist today.

Modes are lexical, semantic, and hybrid, allowing direct comparison. Missing configuration or an unavailable index returns 503; invalid input returns 422. Successful search with no matches returns an empty list. Search and citation endpoints are read-only; indexing is an operator CLI, not a public upload endpoint.

## Ingestion and publication

1. Validate the manifest: unique document IDs/paths, at most 50 files, Markdown inside the knowledge root, at most 100 KB per file and 1 MB total. These are local operator limits, not a hardened hostile-upload service.
2. Normalize line endings and hash each document. Retain service, environment, release, source path, title, and line references.
3. Split by headings and bounded word groups. Count with the actual embedding tokenizer; each title/heading/body input is at most 180 tokens, below MiniLM's 256-token limit. Long sections overlap by 12 words. Reject an unrepresentable token instead of silently truncating.
4. Derive the revision from manifest metadata, source checksums, embedding identity, and chunker version. Derive passage IDs from the revision, document, and chunk ordinal.
5. Embed locally; reject non-finite, zero, wrong-sized, or missing vectors.
6. In one PostgreSQL transaction, serialize publication for the current schema, insert all new rows, and update the active revision pointer. A failure rolls everything back. Old revisions remain available for existing citations.

Retrieval first reads the active revision ID and then uses that exact ID for both candidate queries. A concurrent publication cannot mix candidates from two corpora because old rows are retained. Garbage collection of old revisions is not implemented.

## Ranking decisions

- Keyword search uses weighted PostgreSQL tsvector fields, plainto_tsquery, and ts_rank_cd. It is not BM25. Normal query terms are ANDed after stop-word processing; this intentionally simple baseline can miss long paraphrases. It is not a tuned lexical baseline.
- Semantic search uses exact pgvector cosine distance over the applicable revision, environment, release, and either requested service or global guidance. No approximate index is justified for 20 passages.
- The local model is sentence-transformers/all-MiniLM-L6-v2 through FastEmbed 0.9.1/ONNX CPU, with mean pooling and normalization. The ONNX source is Qdrant/all-MiniLM-L6-v2-onnx at commit d13954661f83248295ba75c1ed411eef3b7b936e. Lock files record dependencies and artifact hashes. This keeps the planned MiniLM baseline without installing PyTorch. Each process serializes calls to its native tokenizer/model instance.
- Take up to 20 candidates per channel. Semantic distance must be at most 0.75; this is an initial heuristic, not a calibrated relevance threshold.
- Merge by reciprocal rank fusion: each channel contributes 1/(60 + rank). Break ties by passage ID. Return at most six passages within 1,200 embedding tokens of title/heading/body context. Response metadata and a future model's full prompt are outside this context count.
- Passage ranking may return multiple sections from one document. Diversity constraints, reranking, approximate search, and tuning require measurements before adding complexity.

## Investigation integration

The worker first persists logs.v1. If retrieval is configured, it constructs a deterministic bounded query from the incident title/description and at most two ERROR messages. It retrieves only the incident service and applicable global guidance and persists the result as runbooks.v1.

The report exposes retrieved_guidance separately from observations. Each guidance item carries the immutable passage ID, corpus revision, citation URL, and its investigation-owned evidence ID. Missing retrieval is reported explicitly while available log evidence remains usable. A reclaimed job reuses a committed runbooks.v1 result rather than silently changing its corpus revision.

Without -Agent this remains evidence collection plus guidance. The opt-in agent can follow permitted dependencies and generate hypotheses; see AGENT.md. It still does not establish semantic claim support automatically. Raw telemetry remains a structured tool query rather than a document embedding corpus.

## Verification and limits

Unit checks cover manifest safety, duplicate documents, empty inputs, chunk limits/overlap, stable and changed revisions, invalid vectors, rank fusion, query validation, missing retrieval, and saved guidance after worker interruption. PostgreSQL checks cover all ranking modes and applicability filters, rollback after model/database failures, concurrent identical ingestion, model identity mismatch, and old citations after reindexing. Tests use explicitly synthetic embeddings to isolate mechanics; actual semantic behavior is checked separately through the running API and the locked model.

scripts/verify_knowledge.py contains six authored development cases. The first live run found the expected document among three returned passages for 2/6 lexical queries, 6/6 semantic queries, and 6/6 hybrid queries. These numbers do not establish a general improvement: the corpus and queries are authored together, the lexical baseline is simple, and there is no held-out diagnosis dataset. Results are preserved in docs/retrieval-development-results.json after verification. The script also checks filtering, token bounds, and citation resolution.

Current limits: English-only baseline; no cache, S3 upload, external ingestion, user upload endpoint, retrieval quality guarantee, source-level snapshot archive, or old-revision garbage collection. Generation is available through the opt-in agent. The small internal studies do not establish diagnosis accuracy. Immutable passages/checksums remain in PostgreSQL; a missing/corrupt configured model fails startup explicitly. SQLite does not emulate retrieval.

## RAG-quality update

Incident environment/release are now persisted and propagated; the first successful knowledge revision and ranking profile are pinned for agent follow-up searches. SearchRequest accepts an explicit revision and an optional experimental profile. The local demo log source returns unavailable for non-local or non-demo-v1 scopes. Request hashes are versioned so older default-scope idempotency keys remain replayable.

The v2 chunker preserves whitespace, Markdown lists, code indentation, and source line ranges while retaining the tokenizer limit. It is not a full Markdown parser and may still split long procedures. Ranking profiles are baseline, query, improved (query plus diversity), and rerank. Experimental profiles shape an OR keyword query, prioritize error-like terms, and optionally limit repeated document sections. The local reranker uses a pinned Xenova MiniLM ONNX model with a raw-score gate of zero; it is not a calibrated confidence filter.

Production uses knowledge/retrieval-config.json and remains baseline after mixed held-out results. Reranker weights are not loaded by default. Prepare experimental weights only when running the operator study:

```powershell
.\.venv\Scripts\python.exe scripts/prepare_embeddings.py --spec knowledge/reranker-lock.json --destination data/embeddings/reranker
```

Evaluation data lives outside application images and production knowledge. The dedicated evaluator compares frozen source and current profiles in owned PostgreSQL schemas without a Gemini key. Do not overwrite frozen study phases or tune using the already-seen held-out set. See RAG_QUALITY_STUDY.md for results, reproduction, and limitations.

## Primary implementation references

- [PostgreSQL text search and ranking](https://www.postgresql.org/docs/17/textsearch-controls.html)
- [pgvector exact and cosine search](https://github.com/pgvector/pgvector)
- [FastEmbed normalized pooled models](https://github.com/qdrant/fastembed/blob/main/fastembed/text/pooled_normalized_embedding.py)

These describe components, not evidence of our application's retrieval quality.
