import json
from types import SimpleNamespace

import pytest
from investigator.knowledge.cache import MAX_VALUE_BYTES, RedisCache, configured_cache
from investigator.knowledge.cached_embeddings import CachedEmbeddings
from investigator.knowledge.store import KnowledgeStore, KnowledgeUnavailable, SearchRequest
from test_knowledge import ToyEmbedder


class MemoryRedis:
    """Protocol fake for deterministic TTL/outage tests; not a Redis performance stand-in."""

    def __init__(self):
        self.values, self.expires = {}, {}
        self.now, self.calls, self.down = 0.0, 0, False

    def check(self):
        self.calls += 1
        if self.down:
            raise OSError("offline")

    def mget(self, keys):
        self.check()
        return [self.values.get(k) if self.expires.get(k, 0) > self.now else None for k in keys]

    def pipeline(self, transaction=False):
        assert transaction is False
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def set(self, key, value, ex):
        self.values[key], self.expires[key] = value, self.now + ex

    def execute(self):
        self.check()
        return []


class CountingEmbedder(ToyEmbedder):
    def __init__(self):
        self.inputs = []

    def embed(self, texts):
        self.inputs.extend(texts)
        # Distinct vectors make order restoration meaningful.
        return [[float(len(t) + 1), 1.0] + [0.0] * 382 for t in texts]


@pytest.fixture
def cache():
    client = MemoryRedis()
    cache = RedisCache(client, "tests", ["database", "schema"], clock=lambda: client.now)
    yield cache
    cache._executor.shutdown(wait=True)


def test_slow_dns_or_server_cannot_block_caller_past_io_deadline(cache):
    import threading
    import time

    release = threading.Event()
    original = cache.client.mget
    cache.client.mget = lambda keys: (release.wait(2), original(keys))[1]
    try:
        started = time.monotonic()
        assert cache.read_many(["one"]) == [None]
        assert time.monotonic() - started < 0.5
        assert cache.metrics.snapshot()["deadline_exceeded"] == 1
        assert cache.read_many(["two"]) == [None]
        assert cache.metrics.snapshot()["bypass"] == 1
    finally:
        release.set()


def test_cache_disabled_does_not_touch_database_or_import_client(monkeypatch):
    assert configured_cache(object()) is None
    monkeypatch.setenv("CACHE_ENABLED", "1")
    with pytest.raises(ValueError, match="requires"):
        configured_cache(object())


def test_api_cache_diagnostics_exposes_only_process_counters(client):
    from investigator.knowledge.cache import CacheMetrics

    response = client.get("/api/diagnostics/cache")
    assert response.headers["cache-control"] == "no-store"
    initial = response.json()
    assert not initial["enabled"] and initial["state"] == "unconfigured"
    assert initial["scope"] == "this API process only" and initial["counters"] == {}
    assert initial["hit_rates"] == {"retrieval": None, "embedding": None}
    metrics = CacheMetrics()
    metrics.add("retrieval_hits", 2)
    client.app.state.knowledge = SimpleNamespace(cache=object(), metrics=metrics)
    assert client.get("/api/diagnostics/cache").json()["counters"] == {"retrieval_hits": 2}


def test_cache_status_reports_real_io_failure_without_probing_or_leaking(client, cache):
    cache.metrics.add("retrieval_hits", 2)
    cache.metrics.add("retrieval_misses", 1)
    cache.metrics.add("secret-cache-url", 1)
    cache.client.down = True
    cache.read_many(["private-query-key"])
    calls = cache.client.calls
    client.app.state.knowledge = SimpleNamespace(cache=cache, metrics=cache.metrics)
    result = client.get("/api/diagnostics/cache")
    value = result.json()
    assert value["enabled"] and value["state"] == "bypassing"
    assert value["bypass_seconds_remaining"] == 5
    assert value["hit_rates"]["retrieval"] == pytest.approx(2 / 3)
    assert value["counters"]["errors"] == 1
    assert cache.client.calls == calls  # Polling must not create health-check traffic.
    assert not value["redis_health_probed"] and value["redis_memory_bytes"] is None
    assert "secret-cache-url" not in result.text and "private-query-key" not in result.text


def test_disabled_cache_still_records_retrieval_latency_and_restart_identity(client):
    from investigator.knowledge.cache import CacheMetrics

    metrics = CacheMetrics()
    metrics.observe_search(0.01, "uncached")
    metrics.observe_search(0.02, "error")
    client.app.state.knowledge = SimpleNamespace(cache=None, metrics=metrics)
    value = client.get("/api/diagnostics/cache").json()
    assert value["state"] == "disabled" and value["knowledge_enabled"]
    assert value["counters"]["search_calls"] == 2 and value["counters"]["search_errors"] == 1
    assert value["latency"]["uncached"] == {"samples": 1, "p50_ms": 10, "p95_ms": 10}
    assert value["latency"]["all"]["samples"] == 1
    restarted = CacheMetrics()
    assert restarted.instance_id != value["process_instance"]
    assert restarted.diagnostics()[1]["all"]["p50_ms"] is None


def test_latency_metrics_are_bounded_thread_safe_and_separate_paths():
    from concurrent.futures import ThreadPoolExecutor

    from investigator.knowledge.cache import CacheMetrics

    metrics = CacheMetrics()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: metrics.observe_search(0.001, "hit"), range(1600)))
    metrics.observe_search(0.02, "miss")
    counters, times = metrics.diagnostics()
    assert counters["search_calls"] == 1601
    assert times["hit"] == {"samples": 512, "p50_ms": 1, "p95_ms": 1}
    assert times["miss"] == {"samples": 1, "p50_ms": 20, "p95_ms": 20}
    assert times["all"]["samples"] == 512


def test_search_instrumentation_preserves_results_and_records_failures(monkeypatch):
    from investigator.knowledge.cache import CacheMetrics

    store = KnowledgeStore.__new__(KnowledgeStore)
    store.metrics = CacheMetrics()
    result = {"hits": [], "query": {"query": "private query"}}
    monkeypatch.setattr(store, "_search", lambda _: (result, "hit"))
    assert store.search(None) is result

    def failed(_):
        raise KnowledgeUnavailable("unavailable")

    monkeypatch.setattr(store, "_search", failed)
    with pytest.raises(KnowledgeUnavailable):
        store.search(None)
    counters, times = store.metrics.diagnostics()
    assert counters["search_calls"] == 2 and counters["search_errors"] == 1
    assert times["hit"]["samples"] == 1 and times["all"]["samples"] == 1


def test_hashed_keys_include_namespace_database_kind_and_scope(cache):
    scope = {"query": "secret incident query", "application": "booking"}
    key = cache.key("embedding", scope)
    assert "secret" not in key and "booking" not in key
    assert key != cache.key("retrieval", scope)
    assert key != RedisCache(None, "other", ["database", "schema"]).key("embedding", scope)
    assert key != RedisCache(None, "tests", ["database", "other"]).key("embedding", scope)
    with pytest.raises(ValueError):
        cache.key("report", scope)


def test_batch_partial_hits_order_duplicates_and_token_limit(cache):
    embedder = CountingEmbedder()
    cached = CachedEmbeddings(embedder, cache)
    first = cached.embed(["one", "longer", "one"], "booking")
    assert embedder.inputs == ["one", "longer"] and first[0] == first[2] != first[1]
    assert cached.embed(["longer", "new", "one"], "booking") == [
        first[1],
        [4.0, 1.0] + [0.0] * 382,
        first[0],
    ]
    assert embedder.inputs == ["one", "longer", "new"]
    cached.embed(["one"], "other-application")
    assert embedder.inputs[-1] == "one" and len(embedder.inputs) == 4
    with pytest.raises(ValueError, match="token limit"):
        cached.embed(["word " * 255], "booking")
    first[0][0] = 900
    assert cached.embed(["one"], "booking")[0][0] == 4.0


@pytest.mark.parametrize(
    "bad",
    [[0.0] * 384, [1.0], [True] * 384, [float("nan")] * 384, [float("inf")] * 384, ["1"] * 384],
)
def test_invalid_cached_vectors_are_recomputed(cache, bad):
    embedder = CountingEmbedder()
    cached = CachedEmbeddings(embedder, cache)
    expected = cached.embed(["payment"], "booking")
    key = next(iter(cache.client.values))
    payload = json.loads(cache.client.values[key])
    payload["vector"] = bad
    cache.client.values[key] = json.dumps(payload).encode()
    assert cached.embed(["payment"], "booking") == expected
    assert len(embedder.inputs) == 2 and cache.metrics.snapshot()["corrupt"] >= 1


def test_expiry_outage_bypass_and_recovery(cache):
    embedder = CountingEmbedder()
    cached = CachedEmbeddings(embedder, cache)
    expected = cached.embed(["payment"], "booking")
    cache.client.now += 30 * 86400 + 1
    assert cached.embed(["payment"], "booking") == expected
    assert len(embedder.inputs) == 2
    cache.client.down = True
    before = cache.client.calls
    assert cached.embed(["payment"], "booking") == expected
    assert cached.embed(["payment"], "booking") == expected
    assert cache.client.calls == before + 1  # no retry, writes also bypassed
    cache.client.down = False
    cache.client.now += 5.01
    assert cached.embed(["payment"], "booking") == expected
    assert len(embedder.inputs) == 4
    assert cache.metrics.snapshot()["errors"] == 1
    assert cache.metrics.snapshot()["bypass"] >= 3


@pytest.mark.parametrize("bad", [b"not json", b"\xff", b"x" * (MAX_VALUE_BYTES + 1), 42])
def test_malformed_payloads_fail_open(cache, bad):
    assert cache.decode(bad) is None
    assert cache.metrics.snapshot()["corrupt"] == 1


def make_store(cache):
    store = KnowledgeStore(
        SimpleNamespace(dialect=SimpleNamespace(name="postgresql")), CountingEmbedder(), cache=cache
    )
    store._resolve_revision = lambda request: request.revision or "a" * 64
    calls = []

    def compute(request, profile, revision):
        from investigator.knowledge.cached_retrieval import LIMITATIONS, RANKING_VERSION

        calls.append(request)
        return {
            "availability": "available",
            "source": "versioned_runbooks",
            "application": request.application,
            "revision": revision,
            "embedding_id": store.embedder.identity,
            "retrieval_config": RANKING_VERSION + ":" + profile,
            "ranking_profile": profile,
            "reranker_id": None,
            "query": request.model_dump(),
            "hits": [],
            "context_tokens": 0,
            "candidate_counts": {"lexical": 0, "semantic": 0},
            "limitations": list(LIMITATIONS),
        }

    store._compute = compute
    return store, calls


def test_successful_empty_retrieval_reconstructs_request_metadata(cache):
    store, calls = make_store(cache)
    request = SearchRequest(query="payment timeout", service="payment")
    first = store.search(request)
    explicit = request.model_copy(update={"revision": "a" * 64, "profile": "baseline"})
    second = store.search(explicit)
    assert len(calls) == 1
    assert second == {**first, "query": explicit.model_dump()}
    second["limitations"].clear()
    assert len(store.search(request)["limitations"]) == 2
    cache.client.now += 3601
    store.search(request)
    assert len(calls) == 2


@pytest.mark.parametrize(
    "change",
    [
        dict(application="booking"),
        dict(service="inventory"),
        dict(environment="staging"),
        dict(release="v2"),
        dict(mode="lexical"),
        dict(limit=2),
        dict(query="other query"),
        dict(profile="query"),
        dict(revision="b" * 64),
    ],
)
def test_retrieval_keys_include_complete_scope(cache, change):
    store, calls = make_store(cache)
    request = SearchRequest(query="payment timeout", service="payment")
    store.search(request)
    store.search(request.model_copy(update=change))
    assert len(calls) == 2


def test_authority_checked_before_hit_and_errors_never_cached(cache):
    store, calls = make_store(cache)
    request = SearchRequest(query="payment timeout", service="payment")
    store.search(request)

    def unavailable(request):
        raise KnowledgeUnavailable("model mismatch or no published knowledge")

    store._resolve_revision = unavailable
    before = cache.client.calls
    with pytest.raises(KnowledgeUnavailable):
        store.search(request)
    assert cache.client.calls == before and len(calls) == 1


def test_corrupt_retrieval_and_incompatible_cache_write_keep_database_result(cache):
    store, calls = make_store(cache)
    request = SearchRequest(query="payment timeout", service="payment")
    original = store.search(request)
    key = next(iter(cache.client.values))
    payload = json.loads(cache.client.values[key])
    payload["content"]["evidence_id"] = "must-never-enter-cache"
    cache.client.values[key] = json.dumps(payload).encode()
    assert store.search(request) == original and len(calls) == 2
    cache.client.values.clear()
    compute = store._compute
    store._compute = lambda *args: {**compute(*args), "future_field": "valid DB output"}
    assert store.search(request)["future_field"] == "valid DB output"
    assert cache.metrics.snapshot()["write_skipped"] == 1
