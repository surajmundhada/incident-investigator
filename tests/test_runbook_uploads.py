import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from investigator.api import create_app
from investigator.catalog import DEMO_CONFIGURATION
from investigator.knowledge.store import KnowledgeConflict, KnowledgeStore, SearchRequest
from investigator.knowledge.uploads import KnowledgeUpload, publish_upload
from investigator.registry import Registry
from pydantic import ValidationError
from test_knowledge import ToyEmbedder


def upload(**changes):
    return {
        "application": DEMO_CONFIGURATION.application,
        "configuration_revision": DEMO_CONFIGURATION.revision,
        "expected_revision": None,
        "replace_application_corpus": True,
        "documents": [
            {
                "id": "payment-guide",
                "title": "Payment recovery",
                "service": "payment",
                "markdown": "# Guide\n\nPayment 503: inspect downstream logs. password=example-secret",
            }
        ],
        **changes,
    }


@pytest.mark.parametrize(
    "change",
    [
        dict(replace_application_corpus=False),
        dict(expected_revision="invalid"),
        dict(documents=[]),
        dict(
            documents=[{"id": "../bad", "title": "Guide", "service": "global", "markdown": "body"}]
        ),
    ],
)
def test_upload_requires_safe_ids_and_explicit_replacement(change):
    with pytest.raises(ValidationError):
        KnowledgeUpload(**upload(**change))


def test_upload_redacts_before_encoder_and_uses_generated_paths():
    def ingest(root, expected_revision):
        assert expected_revision is None
        manifest = json.loads((root / "manifest.json").read_text())
        doc = manifest["documents"][0]
        assert doc["path"] == "payment-guide.md" and doc["application"] == "shopping-demo"
        content = (root / doc["path"]).read_text()
        assert "example-secret" not in content and "[REDACTED]" in content
        return {"revision": "a" * 64}

    registry = SimpleNamespace(revision=lambda rev: DEMO_CONFIGURATION.model_dump())
    assert publish_upload(SimpleNamespace(ingest=ingest), registry, KnowledgeUpload(**upload()))
    with pytest.raises(ValueError, match="registered service"):
        value = upload()
        value["documents"][0]["service"] = "other"
        publish_upload(None, registry, KnowledgeUpload(**value))


def test_upload_endpoint_bounds_and_validation_do_not_echo_content(client, monkeypatch):
    client.app.state.knowledge = object()
    assert (
        client.post(
            "/api/knowledge/documents",
            content=b"x" * 1_100_001,
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/api/knowledge/documents", content=b"abc", headers={"Content-Type": "text/plain"}
        ).status_code
        == 415
    )
    value = upload(unexpected="example-secret")
    response = client.post("/api/knowledge/documents", json=value)
    assert response.status_code == 422 and "example-secret" not in response.text


@pytest.mark.postgres
def test_pg_upload_roundtrip_cas_conflict_and_old_citations(postgres_repo):
    repo, engine, _ = postgres_repo
    store = KnowledgeStore(engine, ToyEmbedder())
    with TestClient(create_app(repo.settings, engine, store)) as client:
        assert (
            client.get("/api/knowledge/head?application=shopping-demo").json()["revision"] is None
        )
        value = upload()
        first = client.post("/api/knowledge/documents", json=value)
        assert first.status_code == 201, first.text
        revision = first.json()["revision"]
        request = SearchRequest(query="payment 503", service="payment")
        old = store.search(request)
        passage = old["hits"][0]["id"]
        assert "example-secret" not in json.dumps(old)
        assert client.post("/api/knowledge/documents", json=value).json()["reused"]
        value["documents"][0]["markdown"] = "# Updated\n\nPayment 503 updated guidance."
        assert client.post("/api/knowledge/documents", json=value).status_code == 409
        assert store.active_revision() == revision
        value["expected_revision"] = revision
        second = client.post("/api/knowledge/documents", json=value)
        assert second.status_code == 201 and second.json()["revision"] != revision
        assert store.passage(passage)["revision_id"] == revision


@pytest.mark.postgres
def test_pg_competing_publishers_cannot_silently_overwrite(postgres_repo):
    from concurrent.futures import ThreadPoolExecutor

    repo, engine, _ = postgres_repo
    registry = Registry(repo.sessions)
    registry.ensure_demo()
    store = KnowledgeStore(engine, ToyEmbedder())
    one, two = upload(), upload()
    two["documents"][0]["markdown"] = "# Other\n\nDifferent payment guidance."

    def publish(value):
        try:
            return publish_upload(store, registry, KnowledgeUpload(**value))
        except KnowledgeConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, [one, two]))
    assert results.count("conflict") == 1
