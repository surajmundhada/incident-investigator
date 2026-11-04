import json
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text

from .corpus import CHUNKER_VERSION, prepare_corpus
from .embeddings import validate_vectors


class KnowledgeUnavailable(Exception):
    pass


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=500)
    service: Literal["checkout", "payment", "inventory"]
    environment: Literal["local", "staging", "production"] = "local"
    release: str = Field(default="demo-v1", pattern=r"^[a-zA-Z0-9_.-]{1,40}$")
    mode: Literal["lexical", "semantic", "hybrid"] = "hybrid"
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


class KnowledgeStore:
    def __init__(self, engine, embedder):
        if engine.dialect.name != "postgresql":
            raise KnowledgeUnavailable("Knowledge retrieval requires PostgreSQL with pgvector")
        self.engine = engine
        self.embedder = embedder

    def passage(self, passage_id):
        with self.engine.begin() as db:
            db.execute(text("SET LOCAL statement_timeout = 5000"))
            row = (
                db.execute(
                    text("""
                SELECT id, revision_id, document_id, source, title, heading, body,
                       document_checksum, line_start, line_end, service, environment, release
                FROM knowledge_chunks WHERE id = :id
            """),
                    {"id": passage_id},
                )
                .mappings()
                .first()
            )
            return dict(row) if row else None

    def ingest(self, root):
        revision, manifest, passages = prepare_corpus(root, self.embedder)
        # Do all potentially failing model work before touching the active revision.
        vectors = validate_vectors(
            self.embedder.embed([passage["embedding_text"] for passage in passages]), len(passages)
        )
        with self.engine.begin() as db:
            db.execute(text("SET LOCAL statement_timeout = 5000"))
            # Schema-scoped serialization also makes concurrent same-revision ingests safe.
            db.execute(text("SELECT pg_advisory_xact_lock(hashtext(current_schema()), 8371)"))
            exists = db.scalar(
                text("SELECT id FROM knowledge_revisions WHERE id = :id"), {"id": revision}
            )
            if not exists:
                db.execute(
                    text("""
                    INSERT INTO knowledge_revisions
                    (id, embedding_id, embedding_spec, manifest, chunker_version, created_at)
                    VALUES (:id, :embedding_id, CAST(:spec AS json), CAST(:manifest AS json), :chunker, :now)
                """),
                    {
                        "id": revision,
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
                        (id, revision_id, document_id, source, title, heading, body, service,
                         environment, release, document_checksum, line_start, line_end, token_count, embedding)
                        VALUES (:id, :revision_id, :document_id, :source, :title, :heading, :body,
                         :service, :environment, :release, :document_checksum, :line_start, :line_end,
                         :token_count, CAST(:embedding AS public.vector))
                    """),
                        {**passage, "embedding": json.dumps(vector)},
                    )
            db.execute(
                text("""
                INSERT INTO knowledge_active(slot, revision_id) VALUES (1, :revision)
                ON CONFLICT (slot) DO UPDATE SET revision_id = EXCLUDED.revision_id
            """),
                {"revision": revision},
            )
        return {
            "revision": revision,
            "documents": len(manifest),
            "passages": len(passages),
            "reused": bool(exists),
        }

    def search(self, request: SearchRequest):
        vector = None
        if request.mode != "lexical":
            # Reject an overlong query explicitly rather than silently truncating embeddings.
            if self.embedder.token_count(request.query) > 256:
                raise ValueError("Query exceeds the embedding token limit")
            vector = validate_vectors(self.embedder.embed([request.query]), 1)[0]
        with self.engine.begin() as db:
            db.execute(text("SET LOCAL statement_timeout = 5000"))
            active = (
                db.execute(
                    text("""
                SELECT r.id, r.embedding_id FROM knowledge_active a
                JOIN knowledge_revisions r ON r.id = a.revision_id WHERE a.slot = 1
            """)
                )
                .mappings()
                .first()
            )
            if not active:
                raise KnowledgeUnavailable("No knowledge revision has been published")
            revision = active["id"]
            if active["embedding_id"] != self.embedder.identity:
                raise KnowledgeUnavailable("Published corpus uses a different embedding model")
            params = {**request.model_dump(), "revision": revision}
            scope = "revision_id = :revision AND environment = :environment AND release = :release AND service IN (:service, 'global')"
            columns = "id, document_id, source, title, heading, body, service, environment, release, document_checksum, line_start, line_end, token_count"
            lexical, semantic = [], []
            if request.mode != "semantic":
                lexical = (
                    db.execute(
                        text(f"""
                    SELECT {columns}, ts_rank_cd(search_tsv, plainto_tsquery('english', :query)) AS lexical_score
                    FROM knowledge_chunks WHERE {scope}
                    AND search_tsv @@ plainto_tsquery('english', :query)
                    ORDER BY lexical_score DESC, id LIMIT 20
                """),
                        params,
                    )
                    .mappings()
                    .all()
                )
            if request.mode != "lexical":
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
        hits, tokens = fuse(lexical, semantic, request.limit)
        for hit in hits:
            hit["citation_url"] = f"/api/knowledge/passages/{hit['id']}"
        return {
            "availability": "available",
            "source": "versioned_runbooks",
            "revision": revision,
            "embedding_id": self.embedder.identity,
            "retrieval_config": "fts-cosine-rrf60-top20-context1200-v1",
            "query": request.model_dump(),
            "hits": hits,
            "context_tokens": tokens,
            "candidate_counts": {"lexical": len(lexical), "semantic": len(semantic)},
            "limitations": [
                "Runbooks are guidance, not observations or proof of a root cause.",
                "Cosine filtering is a heuristic, not calibrated relevance confidence.",
            ],
        }
