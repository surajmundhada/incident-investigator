import json
from types import SimpleNamespace

import pytest
from investigator.knowledge.corpus import Document, chunk_document, load_corpus, prepare_corpus
from investigator.knowledge.embeddings import validate_vectors
from investigator.knowledge.store import KnowledgeUnavailable, SearchRequest, fuse
from investigator.knowledge.tool import RunbookTool
from investigator.schemas import IncidentCreate
from investigator.worker import run_once
from pydantic import ValidationError


class ToyEmbedder:
    """Synthetic vectors for mechanics tests, never a semantic-quality benchmark."""

    identity = "a" * 64
    spec = {"name": "test-only", "dimensions": 384}

    def token_count(self, text):
        return len(text.split()) + 2

    def embed(self, texts):
        return [[1.0] + [0.0] * 383 for _ in texts]


def write_corpus(folder):
    folder.mkdir(parents=True, exist_ok=True)
    documents = []
    for doc_id, service, release, environment in (
        ("payment-current", "payment", "demo-v1", "local"),
        ("payment-old", "payment", "demo-v0", "local"),
        ("payment-staging", "payment", "demo-v1", "staging"),
        ("inventory-current", "inventory", "demo-v1", "local"),
        ("global-current", "global", "demo-v1", "local"),
    ):
        (folder / f"{doc_id}.md").write_text(
            "# Guidance\n\n## Payment errors\n\nPayment 503 requires evidence.\n", encoding="utf-8"
        )
        documents.append(
            {
                "id": doc_id,
                "path": f"{doc_id}.md",
                "title": "Payment 503 guidance",
                "service": service,
                "release": release,
                "environment": environment,
            }
        )
    (folder / "manifest.json").write_text(json.dumps({"documents": documents}), encoding="utf-8")
    return folder


def test_corpus_paths_duplicates_and_empty_documents(tmp_path):
    root = write_corpus(tmp_path)
    manifest_path = root / "manifest.json"
    original = json.loads(manifest_path.read_text())
    manifest = json.loads(json.dumps(original))
    manifest["documents"][0]["path"] = "../outside.md"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="inside"):
        load_corpus(root)
    manifest_path.write_text(json.dumps({"documents": [original["documents"][0]] * 2}))
    with pytest.raises(ValueError, match="unique"):
        load_corpus(root)
    manifest_path.write_text(json.dumps(original))
    (root / original["documents"][0]["path"]).write_text("  ")
    with pytest.raises(ValueError, match="empty"):
        load_corpus(root)


def test_chunk_bounds_citations_and_revisions(tmp_path):
    embedder = ToyEmbedder()
    metadata = Document(
        id="long-document", path="long.md", title="Long operational guide", service="global"
    )
    content = "# Guide\n\n## Symptoms\n" + " ".join(f"word{i}" for i in range(420)) + "\n"
    passages = chunk_document(metadata, content, embedder.token_count)
    assert len(passages) >= 3
    assert all(embedder.token_count(p["embedding_text"]) <= 180 for p in passages)
    assert all(p["line_start"] == 4 and p["line_end"] == 4 for p in passages)
    words = " ".join(p["body"] for p in passages).split()
    assert set(words) == {f"word{i}" for i in range(420)}
    root = write_corpus(tmp_path)
    first = prepare_corpus(root, embedder)
    assert first == prepare_corpus(root, embedder)
    path = root / "payment-current.md"
    path.write_text(path.read_text() + "\nAdditional verification step.\n")
    second = prepare_corpus(root, embedder)
    assert first[0] != second[0]
    assert {p["id"] for p in first[2]}.isdisjoint({p["id"] for p in second[2]})


def test_rrf_rewards_agreement_deduplicates_and_bounds_context():
    def row(key, tokens=100):
        return {"id": key, "token_count": tokens}

    hits, tokens = fuse([row("a"), row("b")], [row("b"), row("c")])
    assert hits[0]["id"] == "b"
    assert len(hits) == 3
    assert hits[0]["lexical_rank"] == 2 and hits[0]["semantic_rank"] == 1
    bounded, used = fuse([row("a", 900), row("b", 500)], [], budget=1200)
    assert [hit["id"] for hit in bounded] == ["a"]
    assert used == 900 and tokens == 300


@pytest.mark.parametrize(
    "vectors,count", [([[0.0] * 384], 1), ([[float("nan")] * 384], 1), ([[1.0] * 383], 1), ([], 1)]
)
def test_invalid_embeddings_are_rejected(vectors, count):
    with pytest.raises(ValueError):
        validate_vectors(vectors, count)


def test_search_validation_and_disabled_api(client):
    assert (
        client.post(
            "/api/knowledge/search", json={"query": "payment 503", "service": "payment"}
        ).status_code
        == 503
    )
    for change in (
        {"query": "  "},
        {"query": "x" * 501},
        {"service": "invalid service"},
        {"limit": 7},
        {"mode": "sql"},
    ):
        with pytest.raises(ValidationError):
            SearchRequest(**({"query": "payment 503", "service": "payment"} | change))


def test_retrieval_outage_does_not_invent_guidance(repo, payload):
    def unavailable(request):
        raise KnowledgeUnavailable("test source down")

    logs = {"availability": "available", "records": [], "truncated": False}
    admitted = repo.admit(IncidentCreate(**payload), "retrieval-down")
    assert run_once(
        repo,
        SimpleNamespace(collect=lambda incident: logs),
        RunbookTool(SimpleNamespace(search=unavailable)),
    )
    report = repo.investigation(admitted["investigation_id"])["report"]
    assert report["knowledge_availability"] == "unavailable"
    assert report["retrieved_guidance"] == []
    assert report["hypotheses"] == [] and report["usage"]["model_calls"] == 0
    assert len(report["evidence_ids"]) == 2


def test_interrupted_worker_reuses_original_knowledge_revision(repo, payload):
    admitted = repo.admit(IncidentCreate(**payload), "retrieval-recovery")
    first = repo.claim(now=100)
    repo.record_evidence(
        first, "logs.v1", {"availability": "available", "records": [], "truncated": False}, now=101
    )
    repo.record_evidence(
        first,
        "runbooks.v1",
        {"availability": "available", "revision": "old-revision", "hits": [{"id": "old-passage"}]},
        now=102,
    )

    def unexpected(*args):
        pytest.fail("Persisted evidence should be reused")

    assert run_once(repo, SimpleNamespace(collect=unexpected), SimpleNamespace(collect=unexpected))
    report = repo.investigation(admitted["investigation_id"])["report"]
    assert report["knowledge_revision"] == "old-revision"
    assert report["retrieved_guidance"][0]["id"] == "old-passage"
