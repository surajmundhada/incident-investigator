"""Operator export of reviewed applicable passages; no evaluation labels or keys."""

import json

from investigator.config import Settings
from investigator.db import make_engine
from sqlalchemy import text

engine = make_engine(Settings.from_env())
try:
    with engine.connect() as db:
        revision = db.scalar(text("SELECT revision_id FROM knowledge_active WHERE slot=1"))
        rows = (
            db.execute(
                text("""SELECT id, document_id, title, heading, body, token_count,
            service, environment, release FROM knowledge_chunks WHERE revision_id=:revision
            AND environment='local' AND release='demo-v1' ORDER BY document_id,line_start,id"""),
                {"revision": revision},
            )
            .mappings()
            .all()
        )
        print(json.dumps({"revision": revision, "passages": [dict(row) for row in rows]}))
finally:
    engine.dispose()
