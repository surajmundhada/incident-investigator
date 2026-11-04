"""Immutable topology revisions and transactional active pointers."""

from sqlalchemy import select, text

from .catalog import DEMO_CONFIGURATION, ApplicationConfiguration
from .models import ApplicationActive, ApplicationRevision


class Registry:
    def __init__(self, sessions):
        self.sessions = sessions

    def register(self, configuration, *, only_if_missing=False):
        with self.sessions.begin() as db:
            if db.bind.dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(hashtext(current_schema()), 8372)"))
            key = (configuration.application, configuration.environment, configuration.release)
            active = db.get(ApplicationActive, key)
            if only_if_missing and active is not None:
                return self._result(db.get(ApplicationRevision, active.revision_id))
            revision = db.get(ApplicationRevision, configuration.revision)
            reused = revision is not None
            if revision is None:
                revision = ApplicationRevision(
                    id=configuration.revision,
                    application=configuration.application,
                    configuration=configuration.canonical(),
                )
                db.add(revision)
                db.flush()
            if active is None:
                db.add(
                    ApplicationActive(
                        application=key[0],
                        environment=key[1],
                        release=key[2],
                        revision_id=revision.id,
                    )
                )
            else:
                active.revision_id = revision.id
            return {**self._result(revision), "reused": reused}

    @staticmethod
    def _result(row):
        return {**row.configuration, "revision": row.id}

    def ensure_demo(self):
        return self.register(DEMO_CONFIGURATION, only_if_missing=True)

    def list(self):
        with self.sessions() as db:
            rows = db.scalars(
                select(ApplicationRevision)
                .join(ApplicationActive, ApplicationActive.revision_id == ApplicationRevision.id)
                .order_by(
                    ApplicationActive.application,
                    ApplicationActive.environment,
                    ApplicationActive.release,
                )
            ).all()
            return [self._result(row) for row in rows]

    def revision(self, revision_id):
        with self.sessions() as db:
            row = db.get(ApplicationRevision, revision_id)
            return self._result(row) if row is not None else None

    @staticmethod
    def resolve(db, request):
        if request.configuration_revision:
            row = db.get(ApplicationRevision, request.configuration_revision)
        else:
            active = db.get(
                ApplicationActive, (request.application, request.environment, request.release)
            )
            row = db.get(ApplicationRevision, active.revision_id) if active else None
        if row is None:
            raise ValueError(
                "Register an application configuration for this environment and release first"
            )
        config = ApplicationConfiguration.model_validate(row.configuration)
        if config.revision != row.id:
            raise ValueError("Stored configuration checksum is invalid")
        if (config.application, config.environment, config.release) != (
            request.application,
            request.environment,
            request.release,
        ):
            raise ValueError("Configuration revision belongs to another application or scope")
        if request.service not in config.services:
            raise ValueError("Service is not registered in the selected application configuration")
        return row
