"""Opt-in single-worker SQLite + fictional evidence preview; no API keys or cloud calls."""

import argparse
import os
import threading
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

from .api import create_app
from .config import Settings
from .db import make_engine, sessions_for
from .fixture_source import make_fixture_server
from .repository import Repository
from .tools import LogTool
from .worker import run_once


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", type=Path, help="Optional preview data directory")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    folder = (args.data_dir or root / "data").resolve()
    folder.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{(folder / 'preview.sqlite3').as_posix()}"
    os.environ["DATABASE_URL"] = url
    os.environ["ALLOW_SQLITE_PREVIEW"] = "1"
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend" / "migrations"))
    command.upgrade(config, "head")
    settings = Settings(url, allow_sqlite_preview=True)
    engine = make_engine(settings)
    repo = Repository(sessions_for(engine), settings)
    source = make_fixture_server(port=0)
    tool = LogTool(f"http://127.0.0.1:{source.server_port}")
    stop = threading.Event()

    def work():
        while not stop.is_set():
            if not run_once(repo, tool):
                stop.wait(0.5)

    source_thread = threading.Thread(target=source.serve_forever, daemon=True)
    worker_thread = threading.Thread(target=work, daemon=True)
    source_thread.start()
    worker_thread.start()
    print(f"Preview API: http://127.0.0.1:{args.port}/docs", flush=True)
    print("SQLite preview | fictional fixture logs | NO LLM, RAG, Redis, or S3", flush=True)
    print(
        "Use an incident window covering the preview startup time to retrieve fixture logs.",
        flush=True,
    )
    try:
        uvicorn.run(create_app(settings, engine), host="127.0.0.1", port=args.port)
    finally:
        stop.set()
        source.shutdown()
        source.server_close()
        source_thread.join(timeout=5)
        worker_thread.join(timeout=10)
        engine.dispose()


if __name__ == "__main__":
    main()
