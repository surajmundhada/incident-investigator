"""Persist retrieval applicability while preserving old idempotency hashes."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "incidents", sa.Column("environment", sa.String(20), nullable=False, server_default="local")
    )
    op.add_column(
        "incidents", sa.Column("release", sa.String(40), nullable=False, server_default="demo-v1")
    )
    op.add_column(
        "incidents",
        sa.Column("request_hash_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade():
    for name in ("request_hash_version", "release", "environment"):
        op.drop_column("incidents", name)
