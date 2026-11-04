"""Optional disposable Redis IO. Never logs keys, values, queries or credentials."""

import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import contextmanager
from urllib.parse import urlsplit

from sqlalchemy import text

CACHE_FORMAT = "ii-cache-v1"
EMBEDDING_TTL = 30 * 24 * 60 * 60
RETRIEVAL_TTL = 60 * 60
MAX_VALUE_BYTES = 256_000
CLIENT_VERSION = "7.4.1"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class CacheMetrics:
    def __init__(self):
        self._values = Counter()
        self._lock = threading.Lock()
        self.started_at = time.time()
        self.instance_id = uuid.uuid4().hex
        self._latencies = {key: deque(maxlen=512) for key in ("all", "hit", "miss", "uncached")}

    def add(self, name, value=1):
        with self._lock:
            self._values[name] += value

    def snapshot(self):
        with self._lock:
            return dict(self._values)

    def observe_search(self, seconds, outcome):
        if outcome not in {"hit", "miss", "uncached", "error"}:
            raise ValueError("Unknown retrieval outcome")
        with self._lock:
            self._values["search_calls"] += 1
            if outcome == "error":
                self._values["search_errors"] += 1
            else:
                self._latencies["all"].append(seconds * 1000)
                self._latencies[outcome].append(seconds * 1000)

    def diagnostics(self):
        with self._lock:
            values = dict(self._values)
            samples = {key: sorted(times) for key, times in self._latencies.items()}

        def summary(times):
            size = len(times)
            return {
                "samples": size,
                "p50_ms": (times[(size - 1) // 2] + times[size // 2]) / 2 if size else None,
                "p95_ms": times[math.ceil(size * 0.95) - 1] if size else None,
            }

        return values, {key: summary(times) for key, times in samples.items()}


class RedisCache:
    def __init__(
        self,
        client,
        namespace,
        database_identity,
        *,
        metrics=None,
        clock=time.monotonic,
        errors=(OSError,),
        embeddings=True,
        retrieval=True,
    ):
        self.client = client
        self.prefix = CACHE_FORMAT + ":" + digest([namespace, database_identity]) + ":"
        self.metrics = metrics or CacheMetrics()
        self.clock, self.errors = clock, errors
        self.embeddings, self.retrieval = embeddings, retrieval
        self._bypass_until = 0.0
        self._state_lock = threading.Lock()
        # Bounded memory and wait time; no distributed locks or correctness dependence.
        self._stripes = [threading.Lock() for _ in range(64)]
        # Socket timeouts do not bound DNS resolution. Bound the caller's whole IO wait
        # and cap outstanding operations; timed-out disposable GET/SET may finish later.
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="cache-io")
        self._io_slots = threading.BoundedSemaphore(8)

    @classmethod
    def connect(cls, url, namespace, database_identity, **kwargs):
        from importlib.metadata import version

        import redis
        from redis.backoff import NoBackoff
        from redis.retry import Retry

        if version("redis") != CLIENT_VERSION:
            raise ValueError("Redis client differs from requirements-cache.lock")
        try:
            parsed = urlsplit(url)
            valid = (
                parsed.scheme in {"redis", "rediss"}
                and parsed.hostname
                and not parsed.query
                and not parsed.fragment
            )
            valid = valid and re.fullmatch(r"/(?:[0-9]|1[0-5])", parsed.path or "/0")
            valid = valid and (parsed.port is None or 1 <= parsed.port <= 65535)
        except ValueError:
            valid = False
        if not valid or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", namespace):
            raise ValueError(
                "Supply a valid cache URL/database and deployment namespace; URL options are forbidden"
            )
        pool = redis.ConnectionPool.from_url(
            url,
            max_connections=8,
            socket_connect_timeout=0.1,
            socket_timeout=0.1,
            retry=Retry(NoBackoff(), 0),
            retry_on_timeout=False,
            retry_on_error=[],
            health_check_interval=0,
            protocol=2,
            decode_responses=False,
            socket_keepalive=True,
        )
        return cls(
            redis.Redis(connection_pool=pool),
            namespace,
            database_identity,
            errors=(redis.exceptions.RedisError, OSError),
            **kwargs,
        )

    def key(self, kind, scope):
        if kind not in {"embedding", "retrieval"}:
            raise ValueError("Unsupported cache kind")
        return self.prefix + kind + ":" + digest(scope)

    def _attempt(self, operation):
        with self._state_lock:
            bypass = self.clock() < self._bypass_until
        if bypass:
            self.metrics.add("bypass")
            return None
        if not self._io_slots.acquire(blocking=False):
            self.metrics.add("capacity_bypass")
            return None
        started = time.perf_counter()
        try:
            self.metrics.add("io_operations")
            future = self._executor.submit(operation)
            future.add_done_callback(lambda _: self._io_slots.release())
            return future.result(timeout=0.15)
        except (FutureTimeout, *self.errors) as exc:
            if isinstance(exc, FutureTimeout):
                self.metrics.add("deadline_exceeded")
            self.metrics.add("errors")
            with self._state_lock:
                self._bypass_until = max(self._bypass_until, self.clock() + 5.0)
            return None
        finally:
            self.metrics.add("io_seconds", time.perf_counter() - started)

    def read_many(self, keys):
        result = []
        for start in range(0, len(keys), 64):
            batch = keys[start : start + 64]
            values = self._attempt(lambda batch=batch: self.client.mget(batch))
            result.extend(
                values
                if isinstance(values, list) and len(values) == len(batch)
                else [None] * len(batch)
            )
        return result

    def write_many(self, values, ttl):
        items = list(values.items())
        for start in range(0, len(items), 64):
            batch = items[start : start + 64]

            def write(batch=batch):
                with self.client.pipeline(transaction=False) as pipeline:
                    for key, value in batch:
                        if len(value) <= MAX_VALUE_BYTES:
                            pipeline.set(key, value, ex=ttl)
                    return pipeline.execute()

            self._attempt(write)

    def read_json(self, key):
        return self.decode(self.read_many([key])[0])

    def decode(self, raw):
        if raw is None:
            return None
        try:
            if not isinstance(raw, (str, bytes)) or len(raw) > MAX_VALUE_BYTES:
                raise ValueError()
            return json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            self.metrics.add("corrupt")
            return None

    @contextmanager
    def singleflight(self, key):
        stripe = self._stripes[int(key[-8:], 16) % len(self._stripes)]
        acquired = stripe.acquire(blocking=False)
        if not acquired:
            self.metrics.add("coalescing_waits")
            acquired = stripe.acquire(timeout=0.15)
            if not acquired:
                self.metrics.add("coalescing_timeouts")
        try:
            yield
        finally:
            if acquired:
                stripe.release()

    def close(self):
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.client.close()
        self.client.connection_pool.disconnect()

    def bypass_seconds_remaining(self):
        with self._state_lock:
            return max(0.0, self._bypass_until - self.clock())


def configured_cache(engine):
    if os.environ.get("CACHE_ENABLED", "0") != "1":
        return None
    url = os.environ.get("CACHE_URL")
    namespace = os.environ.get("CACHE_NAMESPACE")
    if not url or not namespace:
        raise ValueError("Enabled caching requires CACHE_URL and CACHE_NAMESPACE")
    # No credentials/URL query options enter keys. Actual schema prevents test/eval collisions.
    with engine.connect() as db:
        row = db.execute(text("SELECT current_database(), current_schema(), current_user")).one()
    identity = [engine.url.host, engine.url.port or 5432, *row]
    return RedisCache.connect(url, namespace, identity)
