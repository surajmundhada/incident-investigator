"""Disposable upload leases and durable artifact availability metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "investigation_id", sa.String(32), sa.ForeignKey("investigations.id"), nullable=False
        ),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(240), unique=True, nullable=False),
        sa.Column("backend", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.Float(), nullable=False),
        sa.Column("lease_token", sa.String(32)),
        sa.Column("lease_until", sa.Float()),
        sa.Column("error", sa.String(80)),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending_upload','available','failed')", name="valid_artifact_status"
        ),
    )
    op.create_index("ix_artifacts_investigation_id", "artifacts", ["investigation_id"])
    op.create_index("ix_artifacts_status", "artifacts", ["status"])


def downgrade():
    op.drop_table("artifacts")
