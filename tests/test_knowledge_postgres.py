from concurrent.futures import ThreadPoolExecutor

import pytest
from investigator.knowledge.store import KnowledgeStore, KnowledgeUnavailable, SearchRequest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from test_knowledge import ToyEmbedder, write_corpus

pytestmark = pytest.mark.postgres


def test_pg_concurrent_snapshot_upload_is_deduplicated(postgres_repo, payload):
    from investigator.snapshots import SnapshotStore
    from test_snapshots import capture

    repo, engine, _ = postgres_repo
    _, request, _ = capture(repo, payload)
    request = request.model_copy(update={"source_name": "Concurrent synthetic capture"})
    store = SnapshotStore(repo.sessions)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.create(request), range(2)))
    assert results[0]["id"] == results[1]["id"]
    assert sum(result["reused"] for result in results) == 1
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM evidence_snapshots")) == 2


def test_pg_application_heads_candidates_and_citations_are_isolated(postgres_repo, tmp_path):
    import json

    _, engine, _ = postgres_repo
    store = KnowledgeStore(engine, ToyEmbedder())
    demo = store.ingest(write_corpus(tmp_path / "demo"))
    root = write_corpus(tmp_path / "booking")
    manifest = json.loads((root / "manifest.json").read_text())
    for document in manifest["documents"]:
        document["application"] = "booking"
    (root / "manifest.json").write_text(json.dumps(manifest))
    booking = store.ingest(root)
    for mode in ("lexical", "semantic", "hybrid"):
        one = store.search(SearchRequest(query="payment 503", service="payment", mode=mode))
        two = store.search(
            SearchRequest(query="payment 503", service="payment", mode=mode, application="booking")
        )
        assert one["revision"] == demo["revision"]
        assert two["revision"] == booking["revision"]
        assert {hit["application"] for hit in one["hits"]} == {"shopping-demo"}
        assert {hit["application"] for hit in two["hits"]} == {"booking"}
        assert {hit["id"] for hit in one["hits"]}.isdisjoint(hit["id"] for hit in two["hits"])
    passage = two["hits"][0]["id"]
    assert store.passage(passage) is None
    assert store.passage(passage, application="booking")["application"] == "booking"
    with pytest.raises(KnowledgeUnavailable):
        store.search(
            SearchRequest(
                query="payment", service="payment", application="booking", revision=demo["revision"]
            )
        )


def test_pg_registry_concurrent_identical_publication_and_pinned_incident(postgres_repo, payload):
    from investigator.registry import Registry
    from investigator.schemas import IncidentCreate
    from test_applications import booking_configuration

    repo, _, _ = postgres_repo
    registry = Registry(repo.sessions)
    config = booking_configuration()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: registry.register(config), range(2)))
    assert {result["revision"] for result in results} == {config.revision}
    assert sum(result["reused"] for result in results) == 1
    result = repo.admit(
        IncidentCreate(
            **{**payload, "application": "booking", "service": "booking-api", "release": "v1"}
        ),
        "pg-application",
    )
    assert (
        repo.investigation(result["investigation_id"])["incident"]["configuration_revision"]
        == config.revision
    )


def test_pg_hybrid_filters_revisions_services_and_scope(postgres_repo, tmp_path):
    _, engine, _ = postgres_repo
    store = KnowledgeStore(engine, ToyEmbedder())
    store.ingest(write_corpus(tmp_path))
    for mode in ("lexical", "semantic", "hybrid"):
        result = store.search(SearchRequest(query="payment 503", service="payment", mode=mode))
        assert {hit["document_id"] for hit in result["hits"]} == {
            "payment-current",
            "global-current",
        }
        assert result["context_tokens"] <= 1200
        assert all(hit["line_start"] == 5 for hit in result["hits"])
    result = store.search(SearchRequest(query="payment 503", service="payment", release="demo-v0"))
    assert {hit["document_id"] for hit in result["hits"]} == {"payment-old"}
    assert (
        store.search(SearchRequest(query="payment", service="payment", release="unknown"))["hits"]
        == []
    )


def test_pg_embedding_and_database_failure_preserve_published_corpus(
    postgres_repo, tmp_path, monkeypatch
):
    _, engine, _ = postgres_repo
    embedder = ToyEmbedder()
    store = KnowledgeStore(engine, embedder)
    root = write_corpus(tmp_path)
    published = store.ingest(root)
    (root / "payment-current.md").write_text("# Updated\n\nPayment failure changed guidance.\n")
    original_embed = embedder.embed
    monkeypatch.setattr(embedder, "embed", lambda texts: [[float("nan")] * 384 for _ in texts])
    with pytest.raises(ValueError):
        store.ingest(root)
    monkeypatch.setattr(embedder, "embed", original_embed)
    from investigator.knowledge import store as module

    original_prepare = module.prepare_corpus

    def invalid(*args):
        revision, manifest, passages = original_prepare(*args)
        passages[-1]["token_count"] = 999
        return revision, manifest, passages

    monkeypatch.setattr(module, "prepare_corpus", invalid)
    with pytest.raises(IntegrityError):
        store.ingest(root)
    assert (
        store.search(SearchRequest(query="payment", service="payment"))["revision"]
        == published["revision"]
    )
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM knowledge_revisions")) == 1


def test_pg_duplicate_ingestion_and_embedding_mismatch(postgres_repo, tmp_path):
    _, engine, _ = postgres_repo
    store = KnowledgeStore(engine, ToyEmbedder())
    root = write_corpus(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.ingest(root), range(2)))
    assert results[0]["revision"] == results[1]["revision"]
    assert sum(result["reused"] for result in results) == 1
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM knowledge_chunks")) == 5
    other = ToyEmbedder()
    other.identity = "b" * 64
    with pytest.raises(KnowledgeUnavailable, match="different"):
        KnowledgeStore(engine, other).search(SearchRequest(query="payment", service="payment"))


def test_pg_reindex_preserves_old_citations(postgres_repo, tmp_path):
    _, engine, _ = postgres_repo
    store = KnowledgeStore(engine, ToyEmbedder())
    root = write_corpus(tmp_path)
    old = store.ingest(root)
    query = SearchRequest(query="payment", service="payment")
    original_ids = {hit["id"] for hit in store.search(query)["hits"]}
    (root / "payment-current.md").write_text("# New\n\nPayment 503 new guidance.\n")
    new = store.ingest(root)
    assert new["revision"] != old["revision"]
    assert store.search(query)["revision"] == new["revision"]
    with engine.connect() as db:
        ids = set(
            db.scalars(
                text("SELECT id FROM knowledge_chunks WHERE revision_id = :revision"),
                {"revision": old["revision"]},
            )
        )
    assert original_ids.issubset(ids)
    citation = store.passage(next(iter(original_ids)))
    assert citation["revision_id"] == old["revision"]
    assert citation["body"] == "Payment 503 requires evidence."
    assert store.passage("f" * 64) is None


def test_pg_pinned_revision_and_reranker_rejection(postgres_repo, tmp_path):
    from types import SimpleNamespace

    _, engine, _ = postgres_repo
    store = KnowledgeStore(engine, ToyEmbedder())
    root = write_corpus(tmp_path)
    old = store.ingest(root)
    (root / "payment-current.md").write_text("# Updated\n\nPayment new procedure.\n")
    new = store.ingest(root)
    assert new["revision"] != old["revision"]
    pinned = store.search(
        SearchRequest(query="payment", service="payment", revision=old["revision"])
    )
    assert pinned["revision"] == old["revision"]
    with pytest.raises(KnowledgeUnavailable):
        store.search(SearchRequest(query="payment", service="payment", revision="f" * 64))
    store.reranker = SimpleNamespace(
        identity="test-only", score=lambda query, rows: [-5.0] * len(rows)
    )
    result = store.search(SearchRequest(query="payment", service="payment", profile="rerank"))
    assert result["hits"] == [] and result["reranker_id"] == "test-only"
    assert (
        store.search(
            SearchRequest(
                query="payment'); DROP TABLE knowledge_chunks; --",
                service="payment",
                profile="query",
            )
        )["availability"]
        == "available"
    )
