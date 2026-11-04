"""Local process telemetry only; never probe Redis or expose its connection details."""

import time

COUNTERS = {
    "search_calls",
    "search_errors",
    "retrieval_hits",
    "retrieval_misses",
    "embedding_hits",
    "embedding_misses",
    "errors",
    "bypass",
    "capacity_bypass",
    "deadline_exceeded",
    "corrupt",
    "io_operations",
    "io_seconds",
    "encoder_inputs",
    "encoder_inputs_avoided",
    "ranking_executions",
    "ranking_executions_avoided",
    "write_skipped",
    "coalescing_waits",
    "coalescing_timeouts",
    "lexical_queries",
    "semantic_queries",
}


def cache_status(store):
    cache = getattr(store, "cache", None)
    metrics = getattr(store, "metrics", None)
    counters, latency = metrics.diagnostics() if metrics is not None else ({}, {})
    remaining = (
        cache.bypass_seconds_remaining() if hasattr(cache, "bypass_seconds_remaining") else 0
    )

    def rate(kind):
        hits, misses = counters.get(kind + "_hits", 0), counters.get(kind + "_misses", 0)
        return hits / (hits + misses) if hits + misses else None

    return {
        "enabled": cache is not None,
        "knowledge_enabled": store is not None,
        "state": "unconfigured"
        if store is None
        else "disabled"
        if cache is None
        else "bypassing"
        if remaining
        else "enabled",
        "scope": "this API process only",
        "process_instance": getattr(metrics, "instance_id", None),
        "started_at": getattr(metrics, "started_at", None),
        "sampled_at": time.time(),
        "counters": {key: value for key, value in counters.items() if key in COUNTERS},
        "hit_rates": {"retrieval": rate("retrieval"), "embedding": rate("embedding")},
        "latency": latency,
        "latency_samples_per_path_limit": 512,
        "bypass_seconds_remaining": remaining,
        "layers": {
            "retrieval": bool(cache is not None and getattr(cache, "retrieval", True)),
            "embeddings": bool(cache is not None and getattr(cache, "embeddings", True)),
        },
        "redis_health_probed": False,
        "redis_memory_bytes": None,
    }
