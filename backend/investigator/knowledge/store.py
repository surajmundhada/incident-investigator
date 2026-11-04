import json
import time
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text

from investigator.catalog import DEFAULT_APPLICATION, Identifier

from .cache import CACHE_FORMAT, RETRIEVAL_TTL, CacheMetrics, digest
from .cached_embeddings import CachedEmbeddings
from .cached_retrieval import LIMITATIONS, RANKING_VERSION, retrieval_scope, validate_cached
from .corpus import CHUNKER_VERSION, prepare_corpus
from .embeddings import validate_vectors
from .query import keyword_query


class KnowledgeUnavailable(Exception):
    pass


class KnowledgeConflict(Exception):
    pass


UNCONDITIONAL = object()


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=500)
    service: Identifier
    application: Identifier = DEFAULT_APPLICATION
    environment: Literal["local", "staging", "production"] = "local"
    release: str = Field(default="demo-v1", pattern=r"^[a-zA-Z0-9_.-]{1,40}$")
    mode: Literal["lexical", "semantic", "hybrid"] = "hybrid"
    revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    profile: Literal["baseline", "query", "improved", "rerank"] | None = None
    limit: int = Field(default=6, ge=1, le=6)

    @field_validator("query")
    @classmethod
    def meaningful(cls, value):
        if len(value.strip()) < 2:
            raise ValueError("Query cannot be blank")
        return value.strip()


def fuse(lexical, semantic, limit=6, budget=1200):
    candidates = {}
    for name, rows in (("lexical_rank", lexical), ("semantic_rank", semantic)):
        for rank, row in enumerate(rows, 1):
            hit = candidates.setdefault(row["id"], {**dict(row), "rrf_score": 0.0})
            if name in hit:
                continue
            hit[name] = rank
            hit["rrf_score"] += 1 / (60 + rank)
            if "distance" in row:
                hit["distance"] = row["distance"]
    selected, used = [], 0
    for hit in sorted(candidates.values(), key=lambda row: (-row["rrf_score"], row["id"])):
        if used + hit["token_count"] > budget:
            continue
        selected.append(hit)
        used += hit["token_count"]
        if len(selected) == limit:
            break
    return selected, used


def select_context(candidates, limit, *, diversify=False, budget=1200):
    selected, used, counts, seen = [], 0, Counter(), set()
    for hit in candidates:
        normalized = " ".join(hit["body"].lower().split())
        if diversify and (counts[hit["document_id"]] >= 2 or normalized in seen):
            continue
        if used + hit["token_count"] > budget:
            continue
        selected.append(hit)
        used += hit["token_count"]
        counts[hit["document_id"]] += 1
        seen.add(normalized)
        if len(selected) >= limit:
            break
    return selected, used


class KnowledgeStore:
    def __init__(self, engine, embedder, *, profile="baseline", reranker=None, cache=None):
        if engine.dialect.name != "postgresql":
            raise KnowledgeUnavailable("Knowledge retrieval requires PostgreSQL with pgvector")
        self.engine = engine
        self.embedder = embedder
        self.profile, self.reranker = profile, reranker
        self.cache = cache
        self.metrics = cache.metrics if cache is not None else CacheMetrics()
        self.cached_embeddings = (
            CachedEmbeddings(embedder, cache) if cache is not None and cache.embeddings else None
        )

    def active_revision(self, application=DEFAULT_APPLICATION):
        with self.engine.connect() as db:
            revision = db.scalar(
                text(
                    "SELECT revision_id FROM knowledge_application_active WHERE application = :application"
                ),
                {"application": application},
            )
        if not revision:
            raise KnowledgeUnavailable("No knowledge revision has been published")
        return revision

    def head(self, application):
        with self.engine.connect() as db:
            row = (
                db.execute(
                    text("""
                SELECT r.id AS revision, r.manifest, r.embedding_id
                FROM knowledge_application_active a
                JOIN knowledge_revisions r ON a.revision_id = r.id
                WHERE a.application = :app AND r.application = :app
            """),
                    {"app": application},
                )
                .mappings()
                .first()
            )
        return {
            "application": application,
            "revision": row["revision"] if row else None,
            "documents": row["manifest"] if row else [],
            "embedding_id": row["embedding_id"] if row else self.embedder.identity,
        }

    def passage(self, passage_id, application=DEFAULT_APPLICATION):
        with self.engine.begin() as db:
            db.execute(text("SET LOCAL statement_timeout = 5000"))
            row = (
                db.execute(
                    text("""
                SELECT id, revision_id, application, document_id, source, title, heading, body,
                       document_checksum, line_start, line_end, service, environment, release
                FROM knowledge_chunks WHERE id = :id AND application = :application
            """),
                    {"id": passage_id, "application": application},
                )
                .mappings()
                .first()
            )
            return dict(row) if row else None

    def ingest(self, root, *, expected_revision=UNCONDITIONAL):
        revision, manifest, passages = prepare_corpus(root, self.embedder)
        application = manifest[0].get("application", DEFAULT_APPLICATION)
        # Do all potentially failing model work before touching the active revision.
        vectors = validate_vectors(
            self._embed([passage["embedding_text"] for passage in passages], application),
            len(passages),
        )
        with self.engine.begin() as db:
            db.execute(text("SET LOCAL statement_timeout = 5000"))
            # Schema-scoped serialization also makes concurrent same-revision ingests safe.
            db.execute(text("SELECT pg_advisory_xact_lock(hashtext(current_schema()), 8371)"))
            if expected_revision is not UNCONDITIONAL:
                current = db.scalar(
                    text(
                        "SELECT revision_id FROM knowledge_application_active WHERE application = :app"
                    ),
                    {"app": application},
                )
                if current not in {expected_revision, revision}:
                    raise KnowledgeConflict(
                        "Knowledge changed; reload the current revision before publishing"
                    )
            exists = db.scalar(
                text("SELECT id FROM knowledge_revisions WHERE id = :id"), {"id": revision}
            )
            if not exists:
                db.execute(
                    text("""
                    INSERT INTO knowledge_revisions
                    (id, application, embedding_id, embedding_spec, manifest, chunker_version, created_at)
                    VALUES (:id, :application, :embedding_id, CAST(:spec AS json), CAST(:manifest AS json), :chunker, :now)
                """),
                    {
                        "id": revision,
                        "application": application,
                        "embedding_id": self.embedder.identity,
                        "spec": json.dumps(self.embedder.spec),
                        "manifest": json.dumps(manifest),
                        "chunker": CHUNKER_VERSION,
                        "now": time.time(),
                    },
                )
                for passage, vector in zip(passages, vectors, strict=True):
                    db.execute(
                        text("""
                        INSERT INTO knowledge_chunks
                        (id, revision_id, application, document_id, source, title, heading, body, service,
                         environment, release, document_checksum, line_start, line_end, token_count, embedding)
                        VALUES (:id, :revision_id, :application, :document_id, :source, :title, :heading, :body,
                         :service, :environment, :release, :document_checksum, :line_start, :line_end,
                         :token_count, CAST(:embedding AS public.vector))
                    """),
                        {**passage, "embedding": json.dumps(vector)},
                    )
            db.execute(
                text("""
                INSERT INTO knowledge_application_active(application, revision_id) VALUES (:application, :revision)
                ON CONFLICT (application) DO UPDATE SET revision_id = EXCLUDED.revision_id
            """),
                {"revision": revision, "application": application},
            )
            if application == DEFAULT_APPLICATION:
                db.execute(
                    text(
                        "INSERT INTO knowledge_active(slot, revision_id) VALUES (1, :revision) ON CONFLICT (slot) DO UPDATE SET revision_id = EXCLUDED.revision_id"
                    ),
                    {"revision": revision},
                )
        return {
            "revision": revision,
            "application": application,
            "documents": len(manifest),
            "passages": len(passages),
            "reused": bool(exists),
        }

    def close(self):
        if self.cache is not None:
            self.cache.close()

    def _embed(self, texts, application):
        if self.cached_embeddings is not None:
            return self.cached_embeddings.embed(texts, application)
        self.metrics.add("encoder_inputs", len(texts))
        return self.embedder.embed(texts)

    def _resolve_revision(self, request):
        with self.engine.begin() as db:
            db.execute(text("SET LOCAL statement_timeout = 5000"))
            active = (
                db.execute(
                    text("""
                    SELECT r.id, r.embedding_id FROM knowledge_application_active a
                    JOIN knowledge_revisions r ON r.id = a.revision_id
                    WHERE a.application = :application AND r.application = :application
                """)
                    if request.revision is None
                    else text("""
                    SELECT id, embedding_id FROM knowledge_revisions
                    WHERE id = :revision AND application = :application
                """),
                    {"revision": request.revision, "application": request.application},
                )
                .mappings()
                .first()
            )
        if not active:
            raise KnowledgeUnavailable("No knowledge revision has been published")
        if active["embedding_id"] != self.embedder.identity:
            raise KnowledgeUnavailable("Published corpus uses a different embedding model")
        return active["id"]

    def search(self, request: SearchRequest):
        started, outcome = time.perf_counter(), "error"
        try:
            result, outcome = self._search(request)
            return result
        finally:
            self.metrics.observe_search(time.perf_counter() - started, outcome)

    def _search(self, request: SearchRequest):
        profile = request.profile or self.profile
        if profile == "rerank" and self.reranker is None:
            raise KnowledgeUnavailable("The requested reranker is not configured")
        if request.mode != "lexical" and self.embedder.token_count(request.query) > 256:
            raise ValueError("Query exceeds the embedding token limit")
        # Authoritative PostgreSQL checks happen even when a matching cache entry exists.
        revision = self._resolve_revision(request)
        if self.cache is None or not self.cache.retrieval:
            return self._compute(request, profile, revision), "uncached"
        reranker = self.reranker.identity if profile == "rerank" else None
        scope = retrieval_scope(request, revision, self.embedder.identity, profile, reranker)
        key = self.cache.key("retrieval", scope)
        with self.cache.singleflight(key):
            entry = self.cache.read_json(key)
            if entry is not None:
                try:
                    content = validate_cached(entry, scope)
                except (ValueError, TypeError, KeyError):
                    self.metrics.add("corrupt")
                else:
                    self.metrics.add("retrieval_hits")
                    self.metrics.add("ranking_executions_avoided")
                    if request.mode != "lexical":
                        self.metrics.add("encoder_inputs_avoided")
                    return {**content, "query": request.model_dump()}, "hit"
            self.metrics.add("retrieval_misses")
            result = self._compute(request, profile, revision)
            content = {key: value for key, value in result.items() if key != "query"}
            envelope = {"format": CACHE_FORMAT, "scope_digest": digest(scope), "content": content}
            # Only validated successful immutable results (including empty hits) are cached.
            try:
                validate_cached(envelope, scope)
                encoded = json.dumps(envelope, allow_nan=False, separators=(",", ":")).encode()
            except (ValueError, TypeError, OverflowError, RecursionError):
                # An incompatible cache envelope must never discard a successful DB result.
                self.metrics.add("write_skipped")
            else:
                self.cache.write_many({key: encoded}, RETRIEVAL_TTL)
            return result, "miss"

    def _compute(self, request, profile, revision):
        vector = None
        if request.mode != "lexical":
            vector = validate_vectors(self._embed([request.query], request.application), 1)[0]
        self.metrics.add("ranking_executions")
        with self.engine.begin() as db:
            db.execute(text("SET LOCAL statement_timeout = 5000"))
            params = {**request.model_dump(), "revision": revision}
            params["lexical_query"] = (
                request.query if profile == "baseline" else keyword_query(request.query)
            )
            query_function = "plainto_tsquery" if profile == "baseline" else "websearch_to_tsquery"
            scope = "application = :application AND revision_id = :revision AND environment = :environment AND release = :release AND service IN (:service, 'global')"
            columns = "id, application, document_id, source, title, heading, body, service, environment, release, document_checksum, line_start, line_end, token_count"
            lexical, semantic = [], []
            if request.mode != "semantic":
                self.metrics.add("lexical_queries")
                lexical = (
                    db.execute(
                        text(f"""
                    SELECT {columns}, ts_rank_cd(search_tsv, {query_function}('english', :lexical_query)) AS lexical_score
                    FROM knowledge_chunks WHERE {scope}
                    AND search_tsv @@ {query_function}('english', :lexical_query)
                    ORDER BY lexical_score DESC, id LIMIT 20
                """),
                        params,
                    )
                    .mappings()
                    .all()
                )
            if request.mode != "lexical":
                self.metrics.add("semantic_queries")
                params["embedding"] = json.dumps(vector)
                semantic = (
                    db.execute(
                        text(f"""
                    SELECT {columns}, embedding OPERATOR(public.<=>) CAST(:embedding AS public.vector) AS distance
                    FROM knowledge_chunks WHERE {scope}
                    AND (embedding OPERATOR(public.<=>) CAST(:embedding AS public.vector)) <= 0.75
                    ORDER BY distance, id LIMIT 20
                """),
                        params,
                    )
                    .mappings()
                    .all()
                )
        candidates, _ = fuse(lexical, semantic, 20, 10_000)
        if profile == "rerank" and candidates:
            scores = self.reranker.score(request.query, candidates)
            for hit, score in zip(candidates, scores, strict=True):
                hit["rerank_score"] = score
            candidates = sorted(
                (hit for hit in candidates if hit["rerank_score"] >= 0),
                key=lambda hit: (-hit["rerank_score"], hit["id"]),
            )
        hits, tokens = select_context(
            candidates, request.limit, diversify=profile in {"improved", "rerank"}
        )
        for hit in hits:
            hit["citation_url"] = (
                f"/api/knowledge/passages/{hit['id']}?application={request.application}"
            )
        return {
            "availability": "available",
            "source": "versioned_runbooks",
            "application": request.application,
            "revision": revision,
            "embedding_id": self.embedder.identity,
            "retrieval_config": RANKING_VERSION + ":" + profile,
            "ranking_profile": profile,
            "reranker_id": self.reranker.identity if profile == "rerank" else None,
            "query": request.model_dump(),
            "hits": hits,
            "context_tokens": tokens,
            "candidate_counts": {"lexical": len(lexical), "semantic": len(semantic)},
            "limitations": list(LIMITATIONS),
        }
