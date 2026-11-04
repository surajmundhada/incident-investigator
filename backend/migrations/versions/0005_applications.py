"""Application registries, pinned incident configuration, and knowledge isolation."""

import time

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

DEMO_REVISION = "351d992c6b0bcbd9cf1cbd2b0bbb7e8cdf197f5d3bc191c6755c7c57dfb1509f"
DEMO = {
    "application": "shopping-demo",
    "environment": "local",
    "release": "demo-v1",
    "services": {
        "checkout": {"dependencies": ["inventory", "payment"]},
        "inventory": {"dependencies": []},
        "payment": {"dependencies": []},
    },
}


def upgrade():
    op.create_table(
        "application_revisions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("application", sa.String(40), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_application_revisions_application", "application_revisions", ["application"]
    )
    op.create_table(
        "application_active",
        sa.Column("application", sa.String(40), primary_key=True),
        sa.Column("environment", sa.String(20), primary_key=True),
        sa.Column("release", sa.String(40), primary_key=True),
        sa.Column(
            "revision_id", sa.String(64), sa.ForeignKey("application_revisions.id"), nullable=False
        ),
    )
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "INSERT INTO application_revisions (id, application, configuration, created_at) VALUES (:id, 'shopping-demo', :config, :now)"
        ).bindparams(sa.bindparam("config", type_=sa.JSON())),
        {"id": DEMO_REVISION, "config": DEMO, "now": time.time()},
    )
    connection.execute(
        sa.text("INSERT INTO application_active VALUES ('shopping-demo', 'local', 'demo-v1', :id)"),
        {"id": DEMO_REVISION},
    )
    op.add_column(
        "incidents",
        sa.Column("application", sa.String(40), nullable=False, server_default="shopping-demo"),
    )
    # Historical incidents keep a configuration identity. Admission validates the referenced
    # revision/application/scope; the column deliberately avoids SQLite table recreation.
    op.add_column(
        "incidents",
        sa.Column(
            "configuration_revision", sa.String(64), nullable=False, server_default=DEMO_REVISION
        ),
    )
    if connection.dialect.name != "postgresql":
        return
    op.add_column(
        "knowledge_revisions",
        sa.Column("application", sa.String(40), nullable=False, server_default="shopping-demo"),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column("application", sa.String(40), nullable=False, server_default="shopping-demo"),
    )
    op.alter_column("knowledge_chunks", "service", type_=sa.String(40))
    op.create_table(
        "knowledge_application_active",
        sa.Column("application", sa.String(40), primary_key=True),
        sa.Column(
            "revision_id", sa.String(64), sa.ForeignKey("knowledge_revisions.id"), nullable=False
        ),
    )
    op.execute(
        "INSERT INTO knowledge_application_active SELECT 'shopping-demo', revision_id FROM knowledge_active WHERE slot=1"
    )
    op.create_index(
        "knowledge_application_scope",
        "knowledge_chunks",
        ["application", "revision_id", "environment", "release", "service"],
    )


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("knowledge_application_scope", table_name="knowledge_chunks")
        op.drop_table("knowledge_application_active")
        op.drop_column("knowledge_chunks", "application")
        op.drop_column("knowledge_revisions", "application")
        # Retain the widened service column: narrowing could destroy valid operator data.
    op.drop_column("incidents", "configuration_revision")
    op.drop_column("incidents", "application")
    op.drop_table("application_active")
    op.drop_index("ix_application_revisions_application", table_name="application_revisions")
    op.drop_table("application_revisions")
