import time
import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .catalog import DEFAULT_APPLICATION, DEMO_CONFIGURATION
from .db import Base


def new_id():
    return uuid.uuid4().hex


class ApplicationRevision(Base):
    __tablename__ = "application_revisions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    application: Mapped[str] = mapped_column(String(40), index=True)
    configuration: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class ApplicationActive(Base):
    __tablename__ = "application_active"
    application: Mapped[str] = mapped_column(String(40), primary_key=True)
    environment: Mapped[str] = mapped_column(String(20), primary_key=True)
    release: Mapped[str] = mapped_column(String(40), primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("application_revisions.id"))


class EvidenceSnapshot(Base):
    __tablename__ = "evidence_snapshots"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    application: Mapped[str] = mapped_column(String(40), index=True)
    configuration_revision: Mapped[str] = mapped_column(ForeignKey("application_revisions.id"))
    metadata_payload: Mapped[dict] = mapped_column(JSON)
    records: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash_version: Mapped[int] = mapped_column(Integer, default=3)
    application: Mapped[str] = mapped_column(String(40), default=DEFAULT_APPLICATION)
    configuration_revision: Mapped[str] = mapped_column(
        String(64), default=DEMO_CONFIGURATION.revision
    )
    snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    service: Mapped[str] = mapped_column(String(64))
    environment: Mapped[str] = mapped_column(String(20), default="local")
    release: Mapped[str] = mapped_column(String(40), default="demo-v1")
    description: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[float] = mapped_column(Float)
    ends_at: Mapped[float] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    __table_args__ = (CheckConstraint("ends_at > starts_at", name="valid_incident_window"),)


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','complete','failed','cancelled')",
            name="valid_investigation_status",
        ),
    )


class Job(Base):
    __tablename__ = "investigation_jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="nonnegative_job_attempts"),
        CheckConstraint(
            "status IN ('queued','running','complete','failed','cancelled')",
            name="valid_job_status",
        ),
        Index("job_claim_order", "status", "lease_until", "created_at"),
    )


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"))
    tool_call_id: Mapped[str] = mapped_column(String(80))
    collected_at: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("investigation_id", "tool_call_id", name="one_tool_result"),)


class InvestigationEvent(Base):
    __tablename__ = "investigation_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class InvestigationCheckpoint(Base):
    __tablename__ = "investigation_checkpoints"
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), primary_key=True)
    state: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    checksum: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    object_key: Mapped[str] = mapped_column(String(240))
    backend: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending_upload", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[float] = mapped_column(Float, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    __table_args__ = (
        UniqueConstraint("backend", "object_key", name="uq_artifact_backend_object_key"),
        CheckConstraint(
            "status IN ('pending_upload','available','failed')", name="valid_artifact_status"
        ),
    )
