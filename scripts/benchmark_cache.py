"""Local MiniLM/PG cache latency experiment in an owned schema; zero hosted calls.

Run inside the retrieval/agent image with TEST_REDIS_URL and model mounts.
Never imports evaluation data, changes production knowledge, or prints credentials.
"""

import argparse
import json
import os
import statistics
import time
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from investigator.knowledge.cache import RedisCache
from investigator.knowledge.embeddings import LocalEmbedder
from investigator.knowledge.store import KnowledgeStore, SearchRequest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema


def percentile(values, proportion):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * proportion))]


def run(trials):
    url = make_url(os.environ["DATABASE_URL"])
    if url.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL is required")
    # Separate database and random owned schema. Operator must first run verify_postgres.py.
    url = url.set(database="investigator_test")
    admin = create_engine(url)
    schema = "cache_bench_" + uuid.uuid4().hex
    with admin.begin() as db:
        db.execute(CreateSchema(schema))
    scoped = url.update_query_dict({"options": f"-csearch_path={schema},public"})
    engine = create_engine(scoped)
    clients = []
    original = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = scoped.render_as_string(hide_password=False)
    try:
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        embedder = LocalEmbedder(os.environ["KNOWLEDGE_MODEL_DIR"])
        base = KnowledgeStore(engine, embedder)
        corpus = base.ingest(Path("knowledge"))
        queries = [
            "payment unavailable checkout errors",
            "inventory dependency timeout",
            "database connection errors",
            "missing evidence investigation",
        ]
        repeated = [
            SearchRequest(query=queries[i % len(queries)], service="checkout")
            for i in range(trials)
        ]
        unique = [
            SearchRequest(query=f"payment timeout request code {i}", service="checkout")
            for i in range(trials)
        ]
        # One encoder warmup; exclude weight loading and first-run graph setup from latency.
        base.search(repeated[0])
        results = {}
        expected = {}
        for mode in ("disabled", "embeddings", "both"):
            cache = None
            if mode != "disabled":
                cache = RedisCache.connect(
                    os.environ["TEST_REDIS_URL"],
                    schema + "_" + mode,
                    [schema],
                    retrieval=mode == "both",
                )
                assert cache.client.ping()
                clients.append(cache)
            store = KnowledgeStore(engine, embedder, cache=cache)
            for phase, requests in (
                ("cold", repeated[:4]),
                ("warm_repeated", repeated),
                ("unique", unique),
            ):
                before = store.metrics.snapshot()
                latencies = []
                for request in requests:
                    started = time.perf_counter()
                    result = store.search(request)
                    latencies.append((time.perf_counter() - started) * 1000)
                    canonical = json.dumps(result, sort_keys=True, allow_nan=False)
                    key = request.query
                    if mode == "disabled":
                        expected[key] = canonical
                    else:
                        assert canonical == expected[key], "Cache changed retrieval content"
                after = store.metrics.snapshot()
                metrics = {k: v - before.get(k, 0) for k, v in after.items()}
                results[f"{mode}/{phase}"] = {
                    "requests": len(requests),
                    "p50_ms": statistics.median(latencies),
                    "p95_ms": percentile(latencies, 0.95),
                    "metrics": metrics,
                }
        disabled = results["disabled/warm_repeated"]["p50_ms"]
        enabled = results["both/warm_repeated"]["p50_ms"]
        return {
            "kind": "local-cache-latency-v1",
            "trials": trials,
            "corpus": corpus,
            "embedding_id": embedder.identity,
            "same_results": True,
            "repeated_median_improvement_percent": 100 * (disabled - enabled) / disabled,
            "target_20_percent_met": enabled <= disabled * 0.8,
            "measurements": results,
            "limits": [
                "Tiny authored corpus; cache benefit depends on exact repeated queries.",
                "Sequential single-process trials, fixed mode order; not a load test.",
                "Cold four-query measurements are descriptive, not stable percentiles.",
                "Local inference and SQL only; no generative token savings measured.",
            ],
        }
    finally:
        for cache in clients:
            keys = list(cache.client.scan_iter(match=cache.prefix + "*"))
            if keys:
                cache.client.delete(*keys)
            cache.close()
        engine.dispose()
        if original is not None:
            os.environ["DATABASE_URL"] = original
        with admin.begin() as db:
            db.execute(DropSchema(schema, cascade=True))
        admin.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=40)
    args = parser.parse_args()
    if not 8 <= args.trials <= 200:
        parser.error("trials must be between 8 and 200")
    print(json.dumps(run(args.trials), indent=2))
