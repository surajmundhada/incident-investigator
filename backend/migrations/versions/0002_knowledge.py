"""Versioned PostgreSQL full-text and vector knowledge index.

SQLite preview deliberately does not implement semantic retrieval.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    op.execute("""
        CREATE TABLE knowledge_revisions (
            id varchar(64) PRIMARY KEY,
            embedding_id varchar(64) NOT NULL,
            embedding_spec json NOT NULL,
            manifest json NOT NULL,
            chunker_version varchar(80) NOT NULL,
            created_at double precision NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE knowledge_chunks (
            id varchar(64) PRIMARY KEY,
            revision_id varchar(64) NOT NULL REFERENCES knowledge_revisions(id),
            document_id varchar(80) NOT NULL,
            source varchar(200) NOT NULL,
            title varchar(120) NOT NULL,
            heading text NOT NULL,
            body text NOT NULL,
            service varchar(20) NOT NULL,
            environment varchar(20) NOT NULL,
            release varchar(40) NOT NULL,
            document_checksum varchar(64) NOT NULL,
            line_start integer NOT NULL CHECK (line_start > 0),
            line_end integer NOT NULL CHECK (line_end >= line_start),
            token_count integer NOT NULL CHECK (token_count BETWEEN 1 AND 180),
            embedding public.vector(384) NOT NULL,
            search_tsv tsvector GENERATED ALWAYS AS (
                setweight(to_tsvector('english', title), 'A') ||
                setweight(to_tsvector('english', heading), 'B') ||
                setweight(to_tsvector('english', body), 'C')
            ) STORED
        )
    """)
    op.execute("CREATE INDEX knowledge_search ON knowledge_chunks USING gin(search_tsv)")
    op.execute(
        "CREATE INDEX knowledge_scope ON knowledge_chunks(revision_id, environment, release, service)"
    )
    op.execute("""
        CREATE TABLE knowledge_active (
            slot integer PRIMARY KEY CHECK (slot = 1),
            revision_id varchar(64) NOT NULL REFERENCES knowledge_revisions(id)
        )
    """)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        for table in ("knowledge_active", "knowledge_chunks", "knowledge_revisions"):
            op.drop_table(table)
    # Keep the shared extension: other schemas may use it.
