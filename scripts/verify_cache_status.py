"""Ephemeral real-Redis/API status check; main cache mode is never changed.

Uses existing reviewed knowledge read-only, no incidents, model calls or S3 access.
Stops only the two test containers created by this invocation, including on failure.
"""

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import httpx
from start_s3 import executable

ROOT = Path(__file__).resolve().parents[1]
REDIS = (
    "redis:7.4.12-alpine@sha256:8da19c7399dca900c6822a1cf30f9d2285585e2c4b457ff4095b0f4500054d3f"
)


def main():
    docker = executable("docker.exe", "Programs/DockerDesktop/resources/bin/docker.exe")
    suffix = uuid.uuid4().hex[:10]
    redis_name, api_name = "cache-check-redis-" + suffix, "cache-check-api-" + suffix
    created = []

    def run(args, env=None):
        result = subprocess.run(
            [docker, *args], capture_output=True, text=True, env=env, timeout=120
        )
        if result.returncode:
            raise RuntimeError("Docker cache-check operation failed; raw output withheld")
        return result.stdout

    # Read only configuration needed for the isolated API. No model/AWS variables copied.
    worker = json.loads(run(["inspect", "incident-investigator-worker-1"]))[0]
    runtime = dict(value.split("=", 1) for value in worker["Config"]["Env"] if "=" in value)
    network = next(
        name for name in worker["NetworkSettings"]["Networks"] if name.endswith("_default")
    )
    env = os.environ.copy()
    env["DATABASE_URL"] = runtime["DATABASE_URL"]
    try:
        run(
            [
                "run",
                "--rm",
                "-d",
                "--name",
                redis_name,
                "--network",
                network,
                "--memory",
                "128m",
                REDIS,
                "redis-server",
                "--save",
                "",
                "--appendonly",
                "no",
                "--maxmemory",
                "32mb",
                "--maxmemory-policy",
                "allkeys-lru",
            ]
        )
        created.append(redis_name)
        run(
            [
                "run",
                "--rm",
                "-d",
                "--name",
                api_name,
                "--network",
                network,
                "--memory",
                "768m",
                "-p",
                "127.0.0.1:18001:8000",
                "-e",
                "DATABASE_URL",
                "-e",
                "KNOWLEDGE_ENABLED=1",
                "-e",
                "KNOWLEDGE_MODEL_DIR=/models/minilm",
                "-e",
                "HF_HUB_OFFLINE=1",
                "-e",
                "ARTIFACT_BACKEND=disabled",
                "-e",
                "CACHE_ENABLED=1",
                "-e",
                f"CACHE_URL=redis://{redis_name}:6379/0",
                "-e",
                f"CACHE_NAMESPACE=check_{suffix}",
                "-v",
                str(ROOT / "backend") + ":/app/backend:ro",
                "-v",
                str(ROOT / "data/embeddings/minilm") + ":/models/minilm:ro",
                "incident-investigator-s3:local",
                "uvicorn",
                "investigator.api:create_app",
                "--factory",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ],
            env=env,
        )
        created.append(api_name)
        with httpx.Client(base_url="http://127.0.0.1:18001", timeout=20, trust_env=False) as client:
            deadline = time.monotonic() + 90
            while True:
                try:
                    if client.get("/readyz").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError("Temporary API readiness timed out")
                time.sleep(1)

            def status():
                response = client.get("/api/diagnostics/cache")
                response.raise_for_status()
                return response.json()

            first = status()
            assert first["enabled"] and first["counters"].get("search_calls", 0) == 0
            request = {
                "application": "shopping-demo",
                "service": "payment",
                "query": "payment timeout " + suffix,
                "mode": "hybrid",
            }
            one = client.post("/api/knowledge/search", json=request)
            two = client.post("/api/knowledge/search", json=request)
            one.raise_for_status()
            two.raise_for_status()
            assert one.json() == two.json()
            warm = status()
            assert warm["counters"]["retrieval_hits"] == warm["counters"]["retrieval_misses"] == 1
            assert warm["hit_rates"]["retrieval"] == 0.5
            assert warm["latency"]["hit"]["samples"] == warm["latency"]["miss"]["samples"] == 1
            run(["stop", redis_name])  # Only this invocation's disposable Redis.
            request["query"] += " source unavailable"
            fallback = client.post("/api/knowledge/search", json=request)
            fallback.raise_for_status()
            down = status()
            assert down["state"] == "bypassing" and down["counters"]["errors"] >= 1
            assert down["counters"].get("search_errors", 0) == 0
            assert down["counters"]["search_calls"] == 3
            before = down["counters"]["io_operations"]
            assert status()["counters"]["io_operations"] == before
            summary = {
                "enabled_hit_miss_verified": True,
                "retrieval_hit_rate": 0.5,
                "real_redis_outage_fallback_verified": True,
                "status_does_not_probe_redis": True,
                "bounded_latency_samples_verified": True,
                "main_cache_mode_changed": False,
                "model_calls": 0,
                "cloud_calls": 0,
            }
            (ROOT / "work/cache-panel-verification.json").write_text(json.dumps(summary, indent=2))
            print(json.dumps(summary, indent=2))
    finally:
        for name in reversed(created):
            subprocess.run([docker, "stop", name], capture_output=True, timeout=30)


if __name__ == "__main__":
    main()
