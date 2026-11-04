"""Immutable captured log evidence and pinned incident source."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evidence_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("application", sa.String(40), nullable=False),
        sa.Column(
            "configuration_revision",
            sa.String(64),
            sa.ForeignKey("application_revisions.id"),
            nullable=False,
        ),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("records", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_evidence_snapshots_application", "evidence_snapshots", ["application"])
    op.add_column("incidents", sa.Column("snapshot_id", sa.String(64), nullable=True))


def downgrade():
    op.drop_column("incidents", "snapshot_id")
    op.drop_index("ix_evidence_snapshots_application", table_name="evidence_snapshots")
    op.drop_table("evidence_snapshots")
