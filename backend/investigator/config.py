"""Explicit environment configuration; no silent fallback from PostgreSQL."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    evidence_base_url: str = "http://127.0.0.1:8091"
    tool_timeout_seconds: float = 5.0
    lease_seconds: int = 60
    max_attempts: int = 3
    allow_sqlite_preview: bool = False

    def __post_init__(self):
        if not self.database_url or not self.database_url.strip():
            raise ValueError("DATABASE_URL must be explicitly configured")
        if self.database_url.startswith("sqlite") and not self.allow_sqlite_preview:
            raise ValueError(
                "SQLite requires ALLOW_SQLITE_PREVIEW=1; it is not the production queue"
            )
        if self.lease_seconds <= 2 * self.tool_timeout_seconds:
            raise ValueError("Lease must exceed twice the tool timeout")

    @classmethod
    def from_env(cls):
        database_url = os.environ.get("DATABASE_URL", "")
        if not database_url.strip():
            raise ValueError("DATABASE_URL must be explicitly configured")
        return cls(
            database_url=database_url,
            evidence_base_url=os.environ.get("EVIDENCE_BASE_URL", "http://127.0.0.1:8091"),
            allow_sqlite_preview=os.environ.get("ALLOW_SQLITE_PREVIEW") == "1",
        )
