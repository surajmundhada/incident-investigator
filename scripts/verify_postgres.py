"""Run checks against a separately created local test database; never print its URL."""

import os
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

url = make_url(os.environ["DATABASE_URL"])
if url.get_backend_name() != "postgresql":
    raise RuntimeError("This verification requires the local PostgreSQL stack")
admin = create_engine(url, isolation_level="AUTOCOMMIT")
try:
    with admin.connect() as connection:
        exists = connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": "investigator_test"},
        )
        if not exists:
            connection.execute(text("CREATE DATABASE investigator_test"))
finally:
    admin.dispose()
os.environ["TEST_POSTGRES_URL"] = url.set(database="investigator_test").render_as_string(
    hide_password=False
)
raise SystemExit(pytest.main(["-q", "-o", "faulthandler_timeout=30", *sys.argv[1:]]))
