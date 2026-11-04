import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from investigator.knowledge.cache import RedisCache, configured_cache
from investigator.knowledge.store import KnowledgeStore, KnowledgeUnavailable, SearchRequest
from sqlalchemy import text
from test_cache import CountingEmbedder
from test_knowledge import write_corpus

pytestmark = pytest.mark.postgres


@pytest.fixture
def redis_factory(postgres_repo, monkeypatch):
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL is not set; real Redis behavior is not verified")
    _, engine, _ = postgres_repo
    monkeypatch.setenv("CACHE_ENABLED", "1")
    monkeypatch.setenv("CACHE_URL", url)
    monkeypatch.setenv("CACHE_NAMESPACE", "test_" + uuid.uuid4().hex)
    clients = []

    def create():
        cache = configured_cache(engine)
        assert cache.client.ping()  # Integration qualification, never runtime readiness.
        clients.append(cache)
        return cache

    yield create, engine
    for cache in clients:
        # Only keys in this test's random namespace + owned PG schema; never FLUSHDB.
        keys = list(cache.client.scan_iter(match=cache.prefix + "*"))
        if keys:
            cache.client.delete(*keys)
        cache.close()


def test_real_redis_cross_client_revision_corruption_expiry_and_scope(redis_factory, tmp_path):
    factory, engine = redis_factory
    cache1, cache2 = factory(), factory()
    assert cache1.prefix == cache2.prefix
    first = KnowledgeStore(engine, CountingEmbedder(), cache=cache1)
    second = KnowledgeStore(engine, CountingEmbedder(), cache=cache2)
    root = write_corpus(tmp_path)
    old = first.ingest(root)
    second.ingest(root)
    assert second.embedder.inputs == []  # independent indexer reuses batch embedding entries
    query = SearchRequest(query="payment 503", service="payment")
    expected = first.search(query)
    assert second.search(query) == expected
    assert cache2.metrics.snapshot()["retrieval_hits"] == 1
    from investigator.knowledge.diagnostics import cache_status

    before = cache2.metrics.snapshot()["io_operations"]
    status = cache_status(second)
    assert status["hit_rates"]["retrieval"] == 1
    assert status["latency"]["hit"]["samples"] == 1
    assert status["latency"]["miss"]["samples"] == 0
    assert cache2.metrics.snapshot()["io_operations"] == before
    assert len(expected["hits"]) == 2
    for key in cache1.client.scan_iter(match=cache1.prefix + "retrieval:*"):
        cache1.client.set(key, b'{"evidence_id":"wrong shape"}', ex=5)
    assert second.search(query) == expected
    assert cache2.metrics.snapshot()["corrupt"] == 1
    for key in cache1.client.scan_iter(match=cache1.prefix + "retrieval:*"):
        cache1.client.pexpire(key, 1)
    time.sleep(0.02)
    assert second.search(query) == expected
    assert cache2.metrics.snapshot()["retrieval_misses"] == 2
    (root / "payment-current.md").write_text("# Changed\n\nPayment 503 updated guidance.\n")
    new = first.ingest(root)
    assert new["revision"] != old["revision"]
    assert second.search(query)["revision"] == new["revision"]
    pinned = query.model_copy(update={"revision": old["revision"], "profile": "baseline"})
    assert second.search(pinned) == {**expected, "query": pinned.model_dump()}
    with pytest.raises(KnowledgeUnavailable):
        second.search(query.model_copy(update={"application": "booking"}))
    with engine.begin() as db:
        db.execute(
            text("UPDATE knowledge_revisions SET embedding_id = :id WHERE id = :rev"),
            {"id": "different", "rev": new["revision"]},
        )
    with pytest.raises(KnowledgeUnavailable, match="different"):
        second.search(query)


def test_real_redis_concurrent_queries_preserve_results_and_work_accounting(
    redis_factory, tmp_path
):
    factory, engine = redis_factory
    store = KnowledgeStore(engine, CountingEmbedder(), cache=factory())
    store.ingest(write_corpus(tmp_path))
    query = SearchRequest(query="payment 503", service="payment")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.search(query), range(4)))
    assert all(value == results[0] for value in results)
    metrics = store.metrics.snapshot()
    # Thread scheduling need not create contention, and a bounded singleflight
    # wait intentionally permits duplicate computation. Neither a wait counter
    # nor exactly one ranking is guaranteed by the runtime contract.
    rankings = metrics["ranking_executions"]
    assert 1 <= rankings <= 4
    assert rankings + metrics.get("retrieval_hits", 0) == 4
    # Once a completed query has populated Redis, a serial follow-up reuses it.
    before = metrics.get("retrieval_hits", 0)
    assert store.search(query) == results[0]
    assert store.metrics.snapshot()["retrieval_hits"] == before + 1


def test_real_redis_bad_scope_and_server_write_error_fail_open(redis_factory, tmp_path):
    factory, engine = redis_factory
    cache = factory()
    store = KnowledgeStore(engine, CountingEmbedder(), cache=cache)
    store.ingest(write_corpus(tmp_path))
    request = SearchRequest(query="payment 503", service="payment")
    expected = store.search(request)
    for key in cache.client.scan_iter(match=cache.prefix + "retrieval:*"):
        entry = json.loads(cache.client.get(key))
        entry["content"]["hits"][0]["application"] = "other-app"
        cache.client.set(key, json.dumps(entry), ex=3600)
    assert store.search(request) == expected
    # WRONGTYPE is a genuine server response; no special global configuration needed.
    key = cache.key("embedding", {"test": "wrongtype"})
    cache.client.lpush(key, "value")
    cache.write_many({key: b"replacement"}, ttl=0)  # Redis rejects invalid SET expiry
    assert cache.metrics.snapshot()["errors"] == 1
    assert store.search(request) == expected  # bypasses cache; PostgreSQL remains usable


def test_real_client_absent_at_startup_does_not_block_queries(postgres_repo, tmp_path):
    pytest.importorskip("redis")
    _, engine, _ = postgres_repo
    cache = RedisCache.connect("redis://127.0.0.1:1/0", "absent", [uuid.uuid4().hex])
    store = KnowledgeStore(engine, CountingEmbedder(), cache=cache)
    try:
        store.ingest(write_corpus(tmp_path))
        result = store.search(SearchRequest(query="payment 503", service="payment"))
        assert len(result["hits"]) == 2
        assert store.metrics.snapshot()["errors"] == 1
        assert store.metrics.snapshot()["bypass"] >= 1
    finally:
        store.close()
