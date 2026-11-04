"""Transactional admission and leased jobs. PostgreSQL is the intended runtime."""

import hashlib
import json
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError

from .catalog import DEFAULT_APPLICATION
from .models import (
    ApplicationRevision,
    Evidence,
    Incident,
    Investigation,
    InvestigationCheckpoint,
    InvestigationEvent,
    Job,
)
from .registry import Registry
from .snapshots import SnapshotStore


class Conflict(Exception):
    pass


class NotFound(Exception):
    pass


class LostLease(Exception):
    pass


@dataclass(frozen=True)
class Claim:
    job_id: str
    investigation_id: str
    token: str
    attempt: int


class Repository:
    def __init__(self, sessions, settings):
        self.sessions = sessions
        self.settings = settings

    @staticmethod
    def event(db, iid, kind, message):
        db.add(InvestigationEvent(investigation_id=iid, kind=kind, message=message))

    def admit(self, request, key):
        canonical = {
            "title": request.title,
            "service": request.service,
            "description": request.description,
            "starts_at": request.starts_at.timestamp(),
            "ends_at": request.ends_at.timestamp(),
        }
        legacy_digest = (
            hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
            if request.environment == "local"
            and request.release == "demo-v1"
            and request.application == DEFAULT_APPLICATION
            and request.configuration_revision is None
            and request.snapshot_id is None
            else None
        )
        canonical.update(environment=request.environment, release=request.release)
        scoped_digest = (
            hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
            if request.application == DEFAULT_APPLICATION
            and request.configuration_revision is None
            and request.snapshot_id is None
            else None
        )
        identity = {
            **canonical,
            "application": request.application,
            "configuration_revision": request.configuration_revision,
            "snapshot_id": request.snapshot_id,
        }
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        with self.sessions() as db:
            old = db.scalar(select(Incident).where(Incident.idempotency_key == key))
            if old:
                return self._existing(db, old, digest, legacy_digest, scoped_digest)
        try:
            with self.sessions.begin() as db:
                scoped_request = request
                if request.snapshot_id:
                    snapshot = SnapshotStore.resolve(db, request)
                    scoped_request = request.model_copy(
                        update={"configuration_revision": snapshot.configuration_revision}
                    )
                configuration = Registry.resolve(db, scoped_request)
                incident = Incident(
                    idempotency_key=key,
                    request_hash=digest,
                    application=request.application,
                    configuration_revision=configuration.id,
                    snapshot_id=request.snapshot_id,
                    **canonical,
                )
                db.add(incident)
                db.flush()
                investigation = Investigation(incident_id=incident.id)
                db.add(investigation)
                db.flush()
                db.add(Job(investigation_id=investigation.id))
                self.event(
                    db, investigation.id, "queued", "Incident accepted and investigation queued"
                )
                return self._admission(incident, investigation, False)
        except IntegrityError:
            # A concurrent request may win the unique idempotency-key insert.
            with self.sessions() as db:
                old = db.scalar(select(Incident).where(Incident.idempotency_key == key))
                if old is None:
                    raise
                return self._existing(db, old, digest, legacy_digest, scoped_digest)

    @staticmethod
    def _admission(incident, investigation, replayed):
        return {
            "incident_id": incident.id,
            "investigation_id": investigation.id,
            "status": investigation.status,
            "replayed": replayed,
        }

    def _existing(self, db, incident, digest, legacy_digest=None, scoped_digest=None):
        expected = {1: legacy_digest, 2: scoped_digest, 3: digest}.get(
            incident.request_hash_version
        )
        if incident.request_hash != expected:
            raise Conflict("Idempotency key was already used with different incident input")
        investigation = db.scalar(
            select(Investigation).where(Investigation.incident_id == incident.id)
        )
        return self._admission(incident, investigation, True)

    def list_incidents(self, limit=20, offset=0):
        with self.sessions() as db:
            pairs = db.execute(
                select(Incident, Investigation)
                .join(Investigation, Investigation.incident_id == Incident.id)
                .order_by(Incident.created_at.desc(), Incident.id)
                .limit(limit)
                .offset(offset)
            ).all()
            return [
                {
                    "id": i.id,
                    "title": i.title,
                    "service": i.service,
                    "application": i.application,
                    "configuration_revision": i.configuration_revision,
                    "snapshot_id": i.snapshot_id,
                    "environment": i.environment,
                    "release": i.release,
                    "created_at": i.created_at,
                    "investigation_id": v.id,
                    "status": v.status,
                }
                for i, v in pairs
            ]

    def investigation(self, iid):
        with self.sessions() as db:
            v = db.get(Investigation, iid)
            if v is None:
                raise NotFound("Investigation not found")
            i = db.get(Incident, v.incident_id)
            configuration = db.get(ApplicationRevision, i.configuration_revision)
            job = db.scalar(select(Job).where(Job.investigation_id == iid))
            evidence = db.scalars(select(Evidence).where(Evidence.investigation_id == iid)).all()
            return {
                "id": v.id,
                "status": v.status,
                "report": v.report,
                "attempts": job.attempts,
                "created_at": v.created_at,
                "updated_at": v.updated_at,
                "incident": {
                    "id": i.id,
                    "title": i.title,
                    "service": i.service,
                    "application": i.application,
                    "configuration_revision": i.configuration_revision,
                    "snapshot_id": i.snapshot_id,
                    "application_config": configuration.configuration if configuration else None,
                    "environment": i.environment,
                    "release": i.release,
                    "description": i.description,
                    "starts_at": i.starts_at,
                    "ends_at": i.ends_at,
                },
                "evidence": [
                    {
                        "id": e.id,
                        "tool_call_id": e.tool_call_id,
                        "collected_at": e.collected_at,
                        **e.payload,
                    }
                    for e in evidence
                ],
            }

    def progress_status(self, iid):
        with self.sessions() as db:
            status = db.scalar(select(Investigation.status).where(Investigation.id == iid))
            if status is None:
                raise NotFound("Investigation not found")
            return status

    def events(self, iid, after=0):
        with self.sessions() as db:
            if db.get(Investigation, iid) is None:
                raise NotFound("Investigation not found")
            rows = db.scalars(
                select(InvestigationEvent)
                .where(InvestigationEvent.investigation_id == iid, InvestigationEvent.id > after)
                .order_by(InvestigationEvent.id)
                .limit(100)
            ).all()
            return [
                {"id": r.id, "kind": r.kind, "message": r.message, "created_at": r.created_at}
                for r in rows
            ]

    def claim(self, now=None):
        now = time.time() if now is None else now
        eligible = or_(Job.status == "queued", and_(Job.status == "running", Job.lease_until < now))
        with self.sessions.begin() as db:
            job = db.scalar(
                select(Job)
                .where(eligible)
                .order_by(Job.created_at, Job.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            if job.attempts >= self.settings.max_attempts:
                job.status, job.lease_token, job.lease_until = "failed", None, None
                inv = db.get(Investigation, job.investigation_id)
                inv.status, inv.updated_at = "failed", now
                self.event(db, inv.id, "failed", "Worker retry limit exhausted")
                return None
            token, attempt = uuid.uuid4().hex, job.attempts + 1
            # Compare-and-set also protects preview claims; SQLite does not implement SKIP LOCKED.
            result = db.execute(
                update(Job)
                .where(Job.id == job.id, Job.attempts == job.attempts, eligible)
                .values(
                    status="running",
                    lease_token=token,
                    lease_until=now + self.settings.lease_seconds,
                    attempts=attempt,
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                return None
            inv = db.get(Investigation, job.investigation_id)
            inv.status, inv.updated_at = "running", now
            self.event(db, inv.id, "running", f"Worker claimed attempt {attempt}")
            return Claim(job.id, inv.id, token, attempt)

    @staticmethod
    def _owns(claim, now):
        return (
            Job.id == claim.job_id,
            Job.status == "running",
            Job.lease_token == claim.token,
            Job.lease_until > now,
        )

    def _touch(self, db, claim, now):
        result = db.execute(
            update(Job)
            .where(*self._owns(claim, now))
            .values(lease_until=now + self.settings.lease_seconds)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise LostLease("Worker no longer owns this investigation")

    def evidence_for(self, iid, tool_call_id):
        with self.sessions() as db:
            row = db.scalar(
                select(Evidence).where(
                    Evidence.investigation_id == iid, Evidence.tool_call_id == tool_call_id
                )
            )
            return {"id": row.id, **row.payload} if row else None

    def heartbeat(self, claim, now=None):
        with self.sessions.begin() as db:
            self._touch(db, claim, time.time() if now is None else now)

    def checkpoint(self, iid):
        with self.sessions() as db:
            row = db.get(InvestigationCheckpoint, iid)
            return row.state if row else None

    def save_checkpoint(self, claim, state, event=None, now=None):
        now = time.time() if now is None else now
        with self.sessions.begin() as db:
            self._touch(db, claim, now)
            row = db.get(InvestigationCheckpoint, claim.investigation_id)
            if row is None:
                db.add(
                    InvestigationCheckpoint(
                        investigation_id=claim.investigation_id, state=state, updated_at=now
                    )
                )
            else:
                row.state, row.updated_at = state, now
            if event:
                self.event(db, claim.investigation_id, "agent_progress", event)

    def cancel(self, iid):
        with self.sessions.begin() as db:
            # Lock the same job that workers update before changing investigation state.
            job = db.scalar(select(Job).where(Job.investigation_id == iid).with_for_update())
            if job is None:
                raise NotFound("Investigation not found")
            inv = db.get(Investigation, iid)
            if job.status == "cancelled":
                return {"id": iid, "status": "cancelled"}
            if job.status not in {"queued", "running"}:
                raise Conflict("Only queued or running investigations can be cancelled")
            job.status, job.lease_token, job.lease_until = "cancelled", None, None
            inv.status, inv.updated_at = "cancelled", time.time()
            self.event(
                db, iid, "cancelled", "Cancellation recorded; no further owned writes allowed"
            )
            return {"id": iid, "status": "cancelled"}

    def record_evidence(self, claim, tool_call_id, payload, now=None):
        now = time.time() if now is None else now
        with self.sessions.begin() as db:
            self._touch(db, claim, now)
            old = db.scalar(
                select(Evidence).where(
                    Evidence.investigation_id == claim.investigation_id,
                    Evidence.tool_call_id == tool_call_id,
                )
            )
            if old:
                return {"id": old.id, **old.payload}
            row = Evidence(
                investigation_id=claim.investigation_id,
                tool_call_id=tool_call_id,
                collected_at=now,
                payload=payload,
            )
            db.add(row)
            db.flush()
            self.event(
                db,
                claim.investigation_id,
                "evidence",
                f"Tool {tool_call_id} returned {payload['availability']}",
            )
            return {"id": row.id, **payload}

    def finish(self, claim, report, now=None):
        now = time.time() if now is None else now
        with self.sessions.begin() as db:
            result = db.execute(
                update(Job)
                .where(*self._owns(claim, now))
                .values(status="complete", lease_token=None, lease_until=None)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                raise LostLease("Worker no longer owns this investigation")
            inv = db.get(Investigation, claim.investigation_id)
            valid_ids = set(
                db.scalars(select(Evidence.id).where(Evidence.investigation_id == inv.id))
            )
            if not set(report["evidence_ids"]).issubset(valid_ids):
                raise ValueError("Report contains evidence from outside the investigation")
            inv.status, inv.updated_at, inv.report = "complete", now, report
            self.event(
                db, inv.id, "complete", "Investigation finished; inspect report mode and provenance"
            )

    def fail(self, claim):
        now = time.time()
        with self.sessions.begin() as db:
            result = db.execute(
                update(Job)
                .where(*self._owns(claim, now))
                .values(status="failed", lease_token=None, lease_until=None)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                raise LostLease("Worker no longer owns this investigation")
            inv = db.get(Investigation, claim.investigation_id)
            inv.status, inv.updated_at = "failed", now
            self.event(db, inv.id, "failed", "Unexpected worker failure; check local server logs")
