"""Bounded local JSON logs; replace this adapter with Loki in a later increment."""

import json
import logging
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


class Telemetry:
    def __init__(self, service, directory):
        self.service = service
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.handler = RotatingFileHandler(
            directory / f"{service}.jsonl", maxBytes=2_000_000, backupCount=1, encoding="utf-8"
        )
        self.handler.setFormatter(logging.Formatter("%(message)s"))
        self.lock = threading.Lock()
        self.requests = self.errors = 0
        self.seconds = 0.0

    def emit(self, message, level="INFO", **fields):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": self.service,
            "level": level,
            "message": message,
            **fields,
        }
        record = logging.LogRecord(self.service, logging.INFO, "", 0, json.dumps(payload), (), None)
        # Handler.handle holds its lock across rollover and the complete line write.
        self.handler.handle(record)

    def observe(self, elapsed, failed):
        with self.lock:
            self.requests += 1
            self.errors += int(failed)
            self.seconds += elapsed

    def metrics(self):
        with self.lock:
            label = f'service="{self.service}"'
            return (
                f"demo_requests_total{{{label}}} {self.requests}\n"
                f"demo_errors_total{{{label}}} {self.errors}\n"
                f"demo_request_duration_seconds_sum{{{label}}} {self.seconds:.6f}\n"
                f"demo_request_duration_seconds_count{{{label}}} {self.requests}\n"
            )

    def close(self):
        self.handler.close()
