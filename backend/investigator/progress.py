"""SSE transport over committed PostgreSQL events, with bounded connection lifetime."""

import asyncio
import json
import time

from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

TERMINAL = {"complete", "failed", "cancelled"}


def frame(kind, value, event_id=None):
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return prefix + f"event: {kind}\ndata: " + json.dumps(value, separators=(",", ":")) + "\n\n"


async def event_stream(repo, iid, after, request, *, lifetime=30, interval=0.75):
    deadline, heartbeat = time.monotonic() + lifetime, time.monotonic() + 10
    yield "retry: 2000\n\n"
    while time.monotonic() < deadline:
        if await request.is_disconnected():
            return
        try:
            # Read status first: a terminal commit guarantees its events are now visible.
            status = await run_in_threadpool(repo.progress_status, iid)
            rows = await run_in_threadpool(repo.events, iid, after)
        except SQLAlchemyError:
            yield frame("stream_error", {"error": "progress_unavailable"})
            return
        for row in rows:
            after = row["id"]
            yield frame("progress", row, after)
        if status in TERMINAL and len(rows) < 100:
            yield frame("complete", {"status": status, "after": after})
            return
        if len(rows) == 100:
            continue  # Drain persisted pages before sleeping or completing.
        if time.monotonic() >= heartbeat:
            yield ": heartbeat\n\n"
            heartbeat = time.monotonic() + 10
        await asyncio.sleep(interval)
