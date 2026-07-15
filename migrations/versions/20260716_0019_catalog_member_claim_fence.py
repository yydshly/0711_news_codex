"""Fence catalog refresh member claims to one operation attempt."""

import sqlalchemy as sa
from alembic import op

revision = "20260716_0019"
down_revision = "20260716_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    column = sa.Column("claim_attempt_id", sa.Integer(), nullable=True)
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("source_catalog_refresh_members") as batch_op:
            batch_op.add_column(column)
            batch_op.create_foreign_key(
                "fk_source_catalog_refresh_members_claim_attempt_id",
                "operation_attempts",
                ["claim_attempt_id"],
                ["id"],
                ondelete="SET NULL",
            )
    else:
        op.add_column("source_catalog_refresh_members", column)
        op.create_foreign_key(
            "fk_source_catalog_refresh_members_claim_attempt_id",
            "source_catalog_refresh_members",
            "operation_attempts",
            ["claim_attempt_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("source_catalog_refresh_members") as batch_op:
            batch_op.drop_constraint(
                "fk_source_catalog_refresh_members_claim_attempt_id", type_="foreignkey"
            )
            batch_op.drop_column("claim_attempt_id")
    else:
        op.drop_constraint(
            "fk_source_catalog_refresh_members_claim_attempt_id",
            "source_catalog_refresh_members",
            type_="foreignkey",
        )
        op.drop_column("source_catalog_refresh_members", "claim_attempt_id")
