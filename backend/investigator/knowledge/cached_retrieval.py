"""Strict cache envelopes; no investigation-owned state enters retrieval entries."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cache import CACHE_FORMAT, digest

RANKING_VERSION = "fts-cosine-rrf60-top20-context1200-v2"
LIMITATIONS = [
    "Runbooks are guidance, not observations or proof of a root cause.",
    "Cosine filtering is a heuristic, not calibrated relevance confidence.",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class CachedHit(Strict):
    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    application: str
    document_id: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=120)
    heading: str
    body: str
    service: str
    environment: str
    release: str
    document_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    token_count: int = Field(ge=1, le=180)
    rrf_score: float = Field(ge=0)
    lexical_rank: int | None = Field(default=None, ge=1, le=20)
    semantic_rank: int | None = Field(default=None, ge=1, le=20)
    lexical_score: float | None = None
    distance: float | None = None
    rerank_score: float | None = None
    citation_url: str

    @model_validator(mode="after")
    def source_lines(self):
        if self.line_end < self.line_start:
            raise ValueError("Invalid cached source lines")
        return self


class CandidateCounts(Strict):
    lexical: int = Field(ge=0, le=20)
    semantic: int = Field(ge=0, le=20)


class CachedContent(Strict):
    availability: Literal["available"]
    source: Literal["versioned_runbooks"]
    application: str
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    embedding_id: str
    retrieval_config: str
    ranking_profile: str
    reranker_id: str | None
    hits: list[CachedHit] = Field(max_length=6)
    context_tokens: int = Field(ge=0, le=1200)
    candidate_counts: CandidateCounts
    limitations: list[str]


class Envelope(Strict):
    format: Literal["ii-cache-v1"]
    scope_digest: str
    content: CachedContent


def retrieval_scope(request, revision, embedding, profile, reranker):
    return {
        "format": CACHE_FORMAT,
        "revision": revision,
        "application": request.application,
        "environment": request.environment,
        "release": request.release,
        "service": request.service,
        "query": request.query,
        "mode": request.mode,
        "limit": request.limit,
        "ranking": RANKING_VERSION,
        "profile": profile,
        "embedding": embedding,
        "reranker": reranker,
        "cosine_max": 0.75,
        "context_budget": 1200,
        "candidate_limit": 20,
        "rrf_k": 60,
    }


def validate_cached(entry, scope):
    envelope = Envelope.model_validate(entry)
    content = envelope.content
    if envelope.scope_digest != digest(scope) or (
        content.application,
        content.revision,
        content.embedding_id,
        content.ranking_profile,
        content.reranker_id,
        content.retrieval_config,
    ) != (
        scope["application"],
        scope["revision"],
        scope["embedding"],
        scope["profile"],
        scope["reranker"],
        RANKING_VERSION + ":" + scope["profile"],
    ):
        raise ValueError("Cached retrieval scope mismatch")
    if content.limitations != LIMITATIONS or len(content.hits) > scope["limit"]:
        raise ValueError("Invalid cached retrieval contract")
    if content.context_tokens != sum(hit.token_count for hit in content.hits) or len(
        {hit.id for hit in content.hits}
    ) != len(content.hits):
        raise ValueError("Invalid cached context budget or duplicate passages")
    for hit in content.hits:
        if (hit.application, hit.environment, hit.release) != (
            scope["application"],
            scope["environment"],
            scope["release"],
        ) or hit.service not in {scope["service"], "global"}:
            raise ValueError("Invalid cached passage applicability")
        if (
            hit.citation_url
            != f"/api/knowledge/passages/{hit.id}?application={scope['application']}"
        ):
            raise ValueError("Invalid cached citation URL")
    # Preserve exactly which optional ranking fields the computation returned.
    return content.model_dump(exclude_unset=True)
