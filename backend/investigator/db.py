from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import Settings


class Base(DeclarativeBase):
    pass


def make_engine(settings: Settings):
    args = (
        {"check_same_thread": False, "timeout": 10}
        if settings.database_url.startswith("sqlite")
        else {}
    )
    engine = create_engine(settings.database_url, connect_args=args, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def sqlite_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


def sessions_for(engine):
    return sessionmaker(engine, expire_on_commit=False)
