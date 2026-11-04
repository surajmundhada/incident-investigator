"""Object identity belongs to a storage backend, permitting local-to-S3 exports."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    constraints = sa.inspect(op.get_bind()).get_unique_constraints("artifacts")
    legacy = next(c for c in constraints if c["column_names"] == ["object_key"])
    naming = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
    with op.batch_alter_table("artifacts", naming_convention=naming) as batch:
        batch.drop_constraint(legacy["name"] or "uq_artifacts_object_key", type_="unique")
        batch.create_unique_constraint("uq_artifact_backend_object_key", ["backend", "object_key"])


def downgrade():
    # Restoring global uniqueness would discard valid cross-backend metadata.
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT object_key FROM artifacts GROUP BY object_key HAVING COUNT(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicate:
        raise RuntimeError("Cannot downgrade while archives share a key across storage backends")
    with op.batch_alter_table("artifacts") as batch:
        batch.drop_constraint("uq_artifact_backend_object_key", type_="unique")
        batch.create_unique_constraint("uq_artifacts_object_key", ["object_key"])
