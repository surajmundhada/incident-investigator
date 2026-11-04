from alembic import context
from investigator import models  # noqa: F401
from investigator.config import Settings
from investigator.db import Base, make_engine

target_metadata = Base.metadata
settings = Settings.from_env()

if context.is_offline_mode():
    context.configure(
        url=settings.database_url, target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(settings)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
