"""Bounded local read/RAG latency qualification, not an AI-quality or load SLO study."""

import asyncio
import hashlib
import json
import math
import statistics
import time
from pathlib import Path

import httpx

QUERIES = [
    "payment timeout",
    "checkout dependency failures",
    "missing evidence",
    "release correlation",
]


async def measure(concurrency, requests):
    gate = asyncio.Semaphore(concurrency)
    times, identities, errors = [], {}, []
    started = time.perf_counter()
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8001", timeout=20, trust_env=False
    ) as client:

        async def one(index):
            query = QUERIES[index % len(QUERIES)]
            async with gate:
                begin = time.perf_counter()
                try:
                    response = await client.post(
                        "/api/knowledge/search",
                        json={"query": query, "service": "checkout", "mode": "hybrid"},
                    )
                    response.raise_for_status()
                    result = response.json()
                    identity = hashlib.sha256(
                        json.dumps(
                            {"revision": result["revision"], "hits": result["hits"]}, sort_keys=True
                        ).encode()
                    ).hexdigest()
                    if query in identities and identities[query] != identity:
                        raise ValueError("Read identity changed within the same workload")
                    identities[query] = identity
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    errors.append(type(exc).__name__)
                finally:
                    times.append((time.perf_counter() - begin) * 1000)

        await asyncio.gather(*(one(index) for index in range(requests)))
    wall = time.perf_counter() - started
    times.sort()
    return {
        "concurrency": concurrency,
        "requests": requests,
        "errors": len(errors),
        "error_types": sorted(set(errors)),
        "wall_seconds": wall,
        "throughput_requests_per_second": requests / wall,
        "p50_ms": statistics.median(times),
        "p95_ms": times[math.ceil(len(times) * 0.95) - 1],
        "identities": identities,
    }


async def main():
    with httpx.Client(base_url="http://127.0.0.1:8001", timeout=20, trust_env=False) as client:
        status = client.get("/api/diagnostics/cache").json()
        if status["enabled"]:
            raise ValueError(
                "This qualification fixes cache off; do not change runtime mode automatically"
            )
        for query in QUERIES:
            response = client.post(
                "/api/knowledge/search",
                json={"query": query, "service": "checkout", "mode": "hybrid"},
            )
            response.raise_for_status()
    serial = await measure(1, 40)
    parallel = await measure(4, 80)
    same = serial["identities"] == parallel["identities"]
    for result in (serial, parallel):
        del result["identities"]
    summary = {
        "kind": "local_api_read_qualification_v1",
        "cache_enabled": False,
        "workloads": [serial, parallel],
        "same_result_identities": same,
        "model_calls": 0,
        "new_incidents": 0,
        "limits": "One local machine; four fixed queries; warmed encoder; request timing excludes client semaphore wait. Not production throughput/SLO or diagnosis evidence.",
    }
    root = Path(__file__).resolve().parents[1]
    (root / "work/api-read-benchmark.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    if not same or serial["errors"] or parallel["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
