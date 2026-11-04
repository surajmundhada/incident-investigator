"""Initial incident, job, evidence, and progress tables.

Revision ID: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "incidents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("service", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.Float(), nullable=False),
        sa.Column("ends_at", sa.Float(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.CheckConstraint("ends_at > starts_at", name="valid_incident_window"),
    )
    op.create_table(
        "investigations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "incident_id", sa.String(32), sa.ForeignKey("incidents.id"), nullable=False, unique=True
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued','running','complete','failed','cancelled')",
            name="valid_investigation_status",
        ),
    )
    op.create_index("ix_investigations_status", "investigations", ["status"])
    op.create_table(
        "investigation_jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.String(32),
            sa.ForeignKey("investigations.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(32)),
        sa.Column("lease_until", sa.Float()),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.CheckConstraint("attempts >= 0", name="nonnegative_job_attempts"),
        sa.CheckConstraint(
            "status IN ('queued','running','complete','failed','cancelled')",
            name="valid_job_status",
        ),
    )
    op.create_index(
        "job_claim_order", "investigation_jobs", ["status", "lease_until", "created_at"]
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "investigation_id", sa.String(32), sa.ForeignKey("investigations.id"), nullable=False
        ),
        sa.Column("tool_call_id", sa.String(80), nullable=False),
        sa.Column("collected_at", sa.Float(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("investigation_id", "tool_call_id", name="one_tool_result"),
    )
    op.create_table(
        "investigation_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "investigation_id", sa.String(32), sa.ForeignKey("investigations.id"), nullable=False
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_investigation_events_investigation_id", "investigation_events", ["investigation_id"]
    )


def downgrade():
    for name in (
        "investigation_events",
        "evidence",
        "investigation_jobs",
        "investigations",
        "incidents",
    ):
        op.drop_table(name)
