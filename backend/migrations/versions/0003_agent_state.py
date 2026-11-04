"""Application-owned workflow state, fenced by the existing job lease."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "investigation_checkpoints",
        sa.Column(
            "investigation_id", sa.String(32), sa.ForeignKey("investigations.id"), primary_key=True
        ),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )


def downgrade():
    op.drop_table("investigation_checkpoints")
