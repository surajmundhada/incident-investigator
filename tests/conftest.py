import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from investigator.api import create_app
from investigator.config import Settings
from investigator.db import Base, make_engine, sessions_for
from investigator.registry import Registry
from investigator.repository import Repository
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema


@pytest.fixture(autouse=True)
def disable_runtime_knowledge(monkeypatch):
    # Unit tests never implicitly load weights or use deployment configuration.
    monkeypatch.delenv("KNOWLEDGE_ENABLED", raising=False)
    monkeypatch.delenv("AGENT_MODE", raising=False)
    monkeypatch.delenv("CACHE_ENABLED", raising=False)
    monkeypatch.delenv("CACHE_URL", raising=False)
    monkeypatch.delenv("CACHE_NAMESPACE", raising=False)
    monkeypatch.delenv("ALERT_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("ARTIFACT_BACKEND", raising=False)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.sqlite3'}", allow_sqlite_preview=True
    )


@pytest.fixture
def engine(settings):
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    Registry(sessions_for(engine)).ensure_demo()
    yield engine
    engine.dispose()


@pytest.fixture
def repo(engine, settings):
    return Repository(sessions_for(engine), settings)


@pytest.fixture
def client(settings, engine):
    with TestClient(create_app(settings, engine)) as client:
        yield client


@pytest.fixture
def payload():
    end = datetime.now(timezone.utc) - timedelta(seconds=1)
    return {
        "title": "Payment errors",
        "service": "payment",
        "description": "Checkout cannot finish",
        "starts_at": (end - timedelta(minutes=5)).isoformat(),
        "ends_at": end.isoformat(),
    }


@pytest.fixture
def postgres_repo(monkeypatch):
    url = os.environ.get("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL is not set; PostgreSQL concurrency is not verified")
    if make_url(url).get_backend_name() != "postgresql":
        pytest.fail("TEST_POSTGRES_URL must reference PostgreSQL")
    # Each test owns a random schema; application tables are never reused/dropped.
    schema = "test_" + uuid.uuid4().hex
    admin = make_engine(Settings(url))
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema))
    scoped = make_url(url).update_query_dict({"options": f"-csearch_path={schema},public"})
    scoped_url = scoped.render_as_string(hide_password=False)
    settings = Settings(scoped_url)
    engine = make_engine(settings)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend" / "migrations"))
    monkeypatch.setenv("DATABASE_URL", scoped_url)
    command.upgrade(config, "head")
    repo = Repository(sessions_for(engine), settings)
    try:
        yield repo, engine, config
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()
