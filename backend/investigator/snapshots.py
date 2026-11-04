"""Immutable user-supplied log snapshots, with explicit declared coverage."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .agent.security import SECURITY_VERSION, redact
from .catalog import Environment, Identifier, Release
from .models import EvidenceSnapshot
from .registry import Registry
from .schemas import LogRecord


class SnapshotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application: Identifier
    configuration_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    environment: Environment = "local"
    release: Release
    source_name: str = Field(min_length=1, max_length=120)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    covered_services: list[Identifier] = Field(min_length=1, max_length=20)
    records: list[LogRecord] = Field(max_length=2000)
    synthetic_example: bool = False

    @model_validator(mode="after")
    def coverage(self):
        if not timedelta(0) < self.ends_at - self.starts_at <= timedelta(hours=1):
            raise ValueError("Snapshot coverage must be ordered and at most one hour")
        if len(set(self.covered_services)) != len(self.covered_services):
            raise ValueError("Covered service IDs must be unique")
        for record in self.records:
            if (
                record.service not in self.covered_services
                or not self.starts_at <= record.timestamp <= self.ends_at
            ):
                raise ValueError(
                    "Every record must fall within the declared services and time coverage"
                )
        return self


class SnapshotStore:
    def __init__(self, sessions):
        self.sessions = sessions

    @staticmethod
    def summary(row):
        return {
            "id": row.id,
            "application": row.application,
            "configuration_revision": row.configuration_revision,
            "created_at": row.created_at,
            **row.metadata_payload,
        }

    def create(self, request):
        canonical = request.model_dump(mode="json")
        canonical["covered_services"].sort()
        checksum = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        snapshot_id = hashlib.sha256(
            f"snapshot-v1:{SECURITY_VERSION}:{checksum}".encode()
        ).hexdigest()
        with self.sessions() as db:
            config = Registry.resolve(
                db,
                SimpleNamespace(
                    application=request.application,
                    configuration_revision=request.configuration_revision,
                    environment=request.environment,
                    release=request.release,
                    service=request.covered_services[0],
                ),
            )
            services = config.configuration["services"]
            if set(request.covered_services) - services.keys():
                raise ValueError("Coverage includes an unregistered service")
            if any(
                record.dependency and record.dependency not in services
                for record in request.records
            ):
                raise ValueError("Log dependency is not a registered service")
        records = redact([record.model_dump(mode="json") for record in request.records])
        metadata = {
            "source_name": redact(request.source_name),
            "environment": request.environment,
            "release": request.release,
            "starts_at": request.starts_at.timestamp(),
            "ends_at": request.ends_at.timestamp(),
            "covered_services": sorted(request.covered_services),
            "record_count": len(records),
            "records_by_service": {
                service: sum(record["service"] == service for record in records)
                for service in request.covered_services
            },
            "source_checksum": checksum,
            "redaction_version": SECURITY_VERSION,
            "synthetic_example": request.synthetic_example,
            "coverage_basis": "user_declared; completeness is not independently verified",
        }
        try:
            with self.sessions.begin() as db:
                old = db.get(EvidenceSnapshot, snapshot_id)
                if old is not None:
                    return {**self.summary(old), "reused": True}
                row = EvidenceSnapshot(
                    id=snapshot_id,
                    application=request.application,
                    configuration_revision=request.configuration_revision,
                    metadata_payload=metadata,
                    records=records,
                )
                db.add(row)
                db.flush()
                return {**self.summary(row), "reused": False}
        except IntegrityError:
            with self.sessions() as db:
                old = db.get(EvidenceSnapshot, snapshot_id)
                if old is None:
                    raise
                return {**self.summary(old), "reused": True}

    def list(self, application):
        with self.sessions() as db:
            return [
                self.summary(row)
                for row in db.scalars(
                    select(EvidenceSnapshot)
                    .where(EvidenceSnapshot.application == application)
                    .order_by(EvidenceSnapshot.created_at.desc())
                    .limit(100)
                )
            ]

    @staticmethod
    def resolve(db, request):
        row = db.get(EvidenceSnapshot, request.snapshot_id)
        if row is None or row.application != request.application:
            raise ValueError("Snapshot is missing or belongs to another application")
        metadata = row.metadata_payload
        if (metadata["environment"], metadata["release"]) != (request.environment, request.release):
            raise ValueError("Snapshot does not match incident environment and release")
        if (
            request.configuration_revision
            and request.configuration_revision != row.configuration_revision
        ):
            raise ValueError("Snapshot belongs to another configuration revision")
        if (
            not metadata["starts_at"]
            <= request.starts_at.timestamp()
            < request.ends_at.timestamp()
            <= metadata["ends_at"]
        ):
            raise ValueError("Incident window must fit inside declared snapshot coverage")
        if request.service not in metadata["covered_services"]:
            raise ValueError("No declared snapshot coverage for the incident service")
        return row


class EvidenceTools:
    def __init__(self, sessions, live):
        self.sessions, self.live = sessions, live

    def collect(self, incident):
        if not incident.get("snapshot_id"):
            return self.live.collect(incident)
        result = {
            "source": "snapshot_log_adapter",
            "application": incident["application"],
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "snapshot_id": incident["snapshot_id"],
            "service": incident["service"],
            "window": {"start": incident["starts_at"], "end": incident["ends_at"]},
            "availability": "unavailable",
            "records": [],
            "truncated": False,
            "data_origin": "captured",
        }
        with self.sessions() as db:
            row = db.get(EvidenceSnapshot, incident["snapshot_id"])
            if (
                row is None
                or row.application != incident["application"]
                or row.configuration_revision != incident["configuration_revision"]
            ):
                return {**result, "error": "snapshot_scope_mismatch"}
            metadata = row.metadata_payload
            if (metadata["environment"], metadata["release"]) != (
                incident.get("environment", "local"),
                incident.get("release", "demo-v1"),
            ):
                return {**result, "error": "snapshot_scope_mismatch"}
            if incident["service"] not in metadata["covered_services"]:
                return {**result, "error": "service_not_in_snapshot"}
            start, end = incident["starts_at"], incident["ends_at"]
            if not metadata["starts_at"] <= start < end <= metadata["ends_at"]:
                return {**result, "error": "outside_snapshot_coverage"}
            # Original order is retained. Citation indices refer to this persisted tool result.
            records = [
                record
                for record in row.records
                if record["service"] == incident["service"]
                and start <= LogRecord.model_validate(record).timestamp.timestamp() <= end
            ]
            return {
                **result,
                "availability": "available",
                "records": records[:100],
                "truncated": len(records) > 100,
                "coverage_basis": metadata["coverage_basis"],
                "synthetic_example": metadata["synthetic_example"],
                "redaction_version": metadata["redaction_version"],
            }
