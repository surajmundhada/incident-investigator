from pathlib import Path

from alembic import command
from alembic.config import Config
from investigator.config import Settings
from investigator.db import make_engine
from sqlalchemy import inspect


def test_initial_migration_up_and_down(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migration.sqlite3'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("ALLOW_SQLITE_PREVIEW", "1")
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend" / "migrations"))
    command.upgrade(config, "head")
    engine = make_engine(Settings(url, allow_sqlite_preview=True))
    assert {
        "incidents",
        "investigations",
        "investigation_jobs",
        "evidence",
        "investigation_events",
    }.issubset(inspect(engine).get_table_names())
    command.downgrade(config, "base")
    assert "incidents" not in inspect(engine).get_table_names()
    engine.dispose()
