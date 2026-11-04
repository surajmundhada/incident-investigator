import hmac
import os
from contextlib import asynccontextmanager
from threading import BoundedSemaphore
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi import Path as PathParam
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, StreamingResponse

from . import __version__
from .alerts import AlertDelivery, AlertmanagerDelivery
from .artifacts import configured_artifacts
from .catalog import DEFAULT_APPLICATION, ApplicationConfiguration, Identifier
from .config import Settings
from .db import make_engine, sessions_for
from .knowledge.diagnostics import cache_status
from .knowledge.store import KnowledgeConflict, KnowledgeUnavailable, SearchRequest
from .knowledge.tool import configured_store
from .knowledge.uploads import KnowledgeUpload, publish_upload
from .progress import event_stream
from .registry import Registry
from .repository import Conflict, NotFound, Repository
from .schemas import IncidentCreate
from .snapshots import SnapshotCreate, SnapshotStore


def create_app(settings=None, engine=None, knowledge=None, artifacts=None):
    settings = settings or Settings.from_env()
    engine = engine or make_engine(settings)
    repo = Repository(sessions_for(engine), settings)
    registry = Registry(sessions_for(engine))
    snapshots = SnapshotStore(sessions_for(engine))
    stream_slots = BoundedSemaphore(32)
    indexing_slots = BoundedSemaphore(1)
    alert_token = os.environ.get("ALERT_WEBHOOK_TOKEN", "")
    artifacts = artifacts or configured_artifacts(repo)

    @asynccontextmanager
    async def lifespan(app):
        registry.ensure_demo()
        if app.state.knowledge is None:
            app.state.knowledge = configured_store(engine)
        yield
        close = getattr(app.state.knowledge, "close", None)
        if callable(close):
            close()
        engine.dispose()

    app = FastAPI(
        title="Incident Investigator",
        version=__version__,
        lifespan=lifespan,
        description="Durable incident admission and read-only investigations. Report mode and provenance identify evidence-only versus model-backed results.",
    )
    app.state.repository = repo
    app.state.settings = settings
    app.state.knowledge = knowledge
    app.state.artifacts = artifacts

    def artifact_manager():
        if app.state.artifacts is None:
            raise HTTPException(
                503, "Server-side archive is not configured; JSON export remains available"
            )
        return app.state.artifacts

    @app.get("/api/investigations/{iid}/artifacts")
    def list_artifacts(iid: str):
        try:
            return {"items": artifact_manager().list(iid)}
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from None

    @app.post("/api/investigations/{iid}/artifacts", status_code=202)
    def create_artifact(iid: str):
        try:
            return artifact_manager().create(iid)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from None
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except OSError:
            raise HTTPException(503, "Artifact spool is unavailable") from None

    @app.post("/api/artifacts/{artifact_id}/retry", status_code=202)
    def retry_artifact(artifact_id: str):
        try:
            return artifact_manager().retry(artifact_id)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from None
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/artifacts/{artifact_id}/download")
    def download_artifact(artifact_id: str):
        manager = artifact_manager()
        try:
            row = manager.get(artifact_id)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from None
        if row.status != "available" or row.backend != manager.objects.name:
            raise HTTPException(409, "Artifact is not available in the configured backend")
        try:
            valid = manager.objects.verified(row.object_key, row.checksum, row.size)
        except Exception:
            raise HTTPException(
                503, "Artifact integrity or storage could not be verified"
            ) from None
        if not valid:
            raise HTTPException(410, "Archived object is missing")
        if row.backend == "s3":
            return RedirectResponse(
                manager.objects.download(row.object_key),
                status_code=303,
                headers={"Cache-Control": "no-store"},
            )
        return Response(
            manager.objects.path(row.object_key).read_bytes(),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="investigation-{row.investigation_id}.json"',
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/applications")
    def list_applications():
        return {"items": registry.list()}

    @app.post("/api/applications", status_code=201)
    def register_application(configuration: ApplicationConfiguration):
        return registry.register(configuration)

    @app.get("/api/applications/revisions/{revision_id}")
    def application_revision(revision_id: Annotated[str, PathParam(pattern=r"^[a-f0-9]{64}$")]):
        configuration = registry.revision(revision_id)
        if configuration is None:
            raise HTTPException(404, "Application configuration revision not found")
        return configuration

    @app.get("/api/snapshots")
    def list_snapshots(application: Identifier):
        return {"items": snapshots.list(application)}

    @app.post("/api/snapshots", status_code=201)
    async def create_snapshot(request: Request):
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            raise HTTPException(415, "Snapshot uploads require Content-Type: application/json")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 1_000_000:
                raise HTTPException(413, "Snapshot JSON exceeds the 1 MB upload limit")
            body.extend(chunk)
        try:
            payload = SnapshotCreate.model_validate_json(body)
        except ValidationError as exc:
            # Do not echo uploaded log messages or credentials in validation errors.
            raise HTTPException(
                422,
                [
                    {"loc": error["loc"], "msg": error["msg"]}
                    for error in exc.errors(include_input=False, include_context=False)
                ],
            ) from None
        try:
            return snapshots.create(payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get("/api/knowledge/head")
    def knowledge_head(application: Identifier):
        if app.state.knowledge is None:
            raise HTTPException(503, "Knowledge retrieval is not configured")
        try:
            return app.state.knowledge.head(application)
        except SQLAlchemyError:
            raise HTTPException(503, "Knowledge retrieval is unavailable") from None

    @app.post("/api/knowledge/documents", status_code=201)
    async def upload_knowledge(request: Request):
        if app.state.knowledge is None:
            raise HTTPException(503, "Knowledge retrieval is not configured")
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            raise HTTPException(415, "Runbook publication requires application/json")
        if not indexing_slots.acquire(blocking=False):
            raise HTTPException(429, "A runbook publication is already running; retry later")
        try:
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 1_100_000:
                    raise HTTPException(413, "Runbook JSON exceeds the 1.1 MB upload limit")
                body.extend(chunk)
            try:
                upload = KnowledgeUpload.model_validate_json(body)
            except ValidationError as exc:
                raise HTTPException(
                    422,
                    [
                        {"loc": e["loc"], "msg": e["msg"]}
                        for e in exc.errors(include_input=False, include_context=False)
                    ],
                ) from None
            try:
                return await run_in_threadpool(
                    publish_upload, app.state.knowledge, registry, upload
                )
            except KnowledgeConflict as exc:
                raise HTTPException(409, str(exc)) from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            except (SQLAlchemyError, KnowledgeUnavailable, RuntimeError):
                raise HTTPException(
                    503, "Knowledge publication failed; the active corpus was preserved"
                ) from None
        finally:
            indexing_slots.release()

    @app.get("/api/knowledge/passages/{passage_id}")
    def get_passage(
        passage_id: Annotated[str, PathParam(pattern=r"^[a-f0-9]{64}$")],
        application: Identifier = DEFAULT_APPLICATION,
    ):
        if app.state.knowledge is None:
            raise HTTPException(503, "Knowledge retrieval is not configured")
        try:
            passage = app.state.knowledge.passage(passage_id, application=application)
        except (SQLAlchemyError, KnowledgeUnavailable):
            raise HTTPException(503, "Knowledge retrieval is unavailable") from None
        if passage is None:
            raise HTTPException(404, "Passage not found")
        return passage

    @app.post("/api/knowledge/search")
    def search_knowledge(request: SearchRequest):
        if app.state.knowledge is None:
            raise HTTPException(503, "Knowledge retrieval is not configured")
        try:
            return app.state.knowledge.search(request)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except (SQLAlchemyError, KnowledgeUnavailable, RuntimeError):
            raise HTTPException(503, "Knowledge retrieval is unavailable") from None

    @app.get("/healthz")
    def health():
        return {
            "status": "ok",
            "version": __version__,
            "mode": "incident_api",
            "storage": "sqlite_preview" if engine.dialect.name == "sqlite" else "postgresql",
            "knowledge_enabled": app.state.knowledge is not None,
        }

    @app.get("/api/diagnostics/cache")
    def cache_diagnostics(response: Response):
        response.headers["Cache-Control"] = "no-store"
        return cache_status(app.state.knowledge)

    @app.get("/readyz")
    def ready():
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1 FROM incidents LIMIT 1"))
        except SQLAlchemyError:
            raise HTTPException(503, "Database unavailable or migrations not applied") from None
        return {"status": "ready"}

    async def read_alert_body(request: Request, limit=16_000):
        if len(alert_token) < 32:
            raise HTTPException(503, "Alert ingestion is not configured")
        authorization = request.headers.get("authorization", "")
        if len(authorization) > 512 or not hmac.compare_digest(
            authorization.encode(), ("Bearer " + alert_token).encode()
        ):
            raise HTTPException(401, "Invalid alert credentials")
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            raise HTTPException(415, "Alert ingestion requires application/json")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > limit:
                raise HTTPException(413, "Alert delivery exceeds the request size limit")
            body.extend(chunk)
        return body

    @app.post("/api/webhooks/alerts", status_code=202)
    async def receive_alert(request: Request):
        body = await read_alert_body(request)
        try:
            delivery = AlertDelivery.model_validate_json(body)
        except ValidationError as exc:
            raise HTTPException(
                422,
                [
                    {"loc": e["loc"], "msg": e["msg"]}
                    for e in exc.errors(include_input=False, include_context=False)
                ],
            ) from None
        if delivery.status == "resolved":
            return {"status": "ignored", "reason": "resolved_delivery"}
        try:
            return await run_in_threadpool(
                repo.admit, delivery.incident, delivery.idempotency_key()
            )
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/api/webhooks/alertmanager", status_code=202)
    async def receive_alertmanager(request: Request, response: Response):
        body = await read_alert_body(request, limit=64_000)
        try:
            deliveries = AlertmanagerDelivery.model_validate_json(body).normalized()
        except (ValidationError, ValueError):
            # Model validator text can include native annotation contents. Never echo it.
            raise HTTPException(
                422,
                "Invalid native alert delivery; check bounded version-4 scope and closed-window fields",
            ) from None
        results, status_code = [], 202
        for index, delivery in enumerate(deliveries):
            if delivery is None:
                results.append({"index": index, "status": "ignored", "reason": "resolved_delivery"})
                continue
            try:
                admitted = await run_in_threadpool(
                    repo.admit, delivery.incident, delivery.idempotency_key()
                )
                results.append(
                    {
                        "index": index,
                        **admitted,
                        "status": "accepted",
                        "investigation_status": admitted["status"],
                    }
                )
            except Conflict:
                results.append({"index": index, "status": "conflict"})
                status_code = 409
            except ValueError:
                results.append(
                    {"index": index, "status": "rejected", "reason": "invalid_registered_scope"}
                )
                if status_code != 409:
                    status_code = 422
        # Each entry commits independently. Exact batch retries reuse admitted jobs.
        response.status_code = status_code
        return {"items": results, "atomicity": "per_alert"}

    @app.post("/api/incidents", status_code=202)
    def create_incident(
        payload: IncidentCreate,
        response: Response,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=160)],
    ):
        if not idempotency_key.strip():
            raise HTTPException(422, "Idempotency-Key cannot be blank")
        try:
            admitted = repo.admit(payload, idempotency_key)
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        response.headers["Location"] = f"/api/investigations/{admitted['investigation_id']}"
        return admitted

    @app.get("/api/incidents")
    def list_incidents(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        return {"items": repo.list_incidents(limit, offset), "limit": limit, "offset": offset}

    @app.get("/api/investigations/{iid}")
    def get_investigation(iid: str):
        try:
            return repo.investigation(iid)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from None

    @app.get("/api/investigations/{iid}/events")
    def get_events(iid: str, after: int = Query(0, ge=0)):
        # Retain JSON polling as a fallback and for bounded operator reads.
        try:
            return {"items": repo.events(iid, after)}
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from None

    @app.get("/api/investigations/{iid}/events/stream")
    def stream_events(
        iid: str,
        request: Request,
        after: int = Query(0, ge=0),
        last_event_id: Annotated[str | None, Header(max_length=20)] = None,
    ):
        if last_event_id is not None:
            if not last_event_id.isascii() or not last_event_id.isdigit():
                raise HTTPException(422, "Last-Event-ID must be a nonnegative event ID")
            after = max(after, int(last_event_id))
        if after > 9_223_372_036_854_775_807:
            raise HTTPException(422, "Event cursor exceeds the supported range")
        try:
            repo.progress_status(iid)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from None
        if not stream_slots.acquire(blocking=False):
            raise HTTPException(503, "Progress stream capacity reached; use JSON polling")

        async def stream():
            try:
                async for message in event_stream(repo, iid, after, request):
                    yield message
            finally:
                stream_slots.release()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/investigations/{iid}/cancel")
    def cancel_investigation(iid: str):
        try:
            return repo.cancel(iid)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from None
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None

    return app
