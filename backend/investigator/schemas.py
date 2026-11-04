from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .catalog import DEFAULT_APPLICATION, Identifier


class IncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=200)
    service: Identifier
    application: Identifier = DEFAULT_APPLICATION
    configuration_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    snapshot_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    environment: Literal["local", "staging", "production"] = "local"
    release: str = Field(default="demo-v1", pattern=r"^[a-zA-Z0-9_.-]{1,40}$")
    description: str = Field(min_length=3, max_length=4000)
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @field_validator("title", "description")
    @classmethod
    def meaningful_text(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("Must contain at least three non-whitespace characters")
        return value.strip()

    @model_validator(mode="after")
    def valid_window(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.ends_at - self.starts_at > timedelta(hours=1):
            raise ValueError("Investigation windows are limited to one hour")
        if self.ends_at > datetime.now(timezone.utc) + timedelta(minutes=1):
            raise ValueError("Window cannot be in the future")
        return self


class LogRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: AwareDatetime
    service: Identifier
    level: Literal["INFO", "WARNING", "ERROR"]
    message: str = Field(min_length=1, max_length=2000)
    request_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    dependency: Identifier | None = None
    status_code: int | None = Field(default=None, ge=100, le=599)
    duration_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class LogBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    records: list[LogRecord] = Field(max_length=100)
    truncated: bool = False
    origin: Literal["live", "fixture"] = "live"
