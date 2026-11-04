"""Read-only adapter over bounded live demo logs. No access to fault controls."""

import json
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from investigator.schemas import LogBatch, LogRecord


def create_app(directory=None):
    directory = Path(directory or os.environ.get("TELEMETRY_DIR", "/telemetry"))
    app = FastAPI(title="Live demo log source")

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/evidence/logs", response_model=LogBatch)
    def logs(
        service: Literal["checkout", "payment", "inventory"],
        start: float = Query(ge=0),
        end: float = Query(ge=0),
        limit: int = Query(default=100, ge=1, le=100),
    ):
        if end <= start or end - start > 3600:
            raise HTTPException(422, "An ordered window of at most one hour is required")
        records = []
        found = False
        rotated = directory / f"{service}.jsonl.1"
        try:
            for path in (rotated, directory / f"{service}.jsonl"):
                try:
                    handle = path.open(encoding="utf-8")
                except FileNotFoundError:
                    continue
                found = True
                with handle:
                    # Each writer retains only two ~2 MB files; guard corrupted files too.
                    if os.fstat(handle.fileno()).st_size > 2_100_000:
                        raise ValueError("Log file exceeds configured retention bound")
                    for line in handle:
                        record = LogRecord.model_validate(json.loads(line))
                        if (
                            record.service == service
                            and start <= record.timestamp.timestamp() <= end
                        ):
                            records.append(record)
            if not found:
                raise HTTPException(503, "Service telemetry is not available")
        except (OSError, ValueError):
            raise HTTPException(503, "Service telemetry could not be read") from None
        records.sort(key=lambda record: record.timestamp)
        return LogBatch(
            records=records[:limit],
            origin="live",
            # Rotation means older coverage cannot be guaranteed, even under the limit.
            truncated=len(records) > limit or rotated.exists(),
        )

    return app
