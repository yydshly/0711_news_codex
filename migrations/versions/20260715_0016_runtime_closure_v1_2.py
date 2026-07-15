"""Add non-destructive current/archive state to the source catalog."""

import sqlalchemy as sa
from alembic import op

revision = "20260715_0016"
down_revision = "20260715_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    state = sa.Column(
        "catalog_state", sa.String(16), nullable=False, server_default=sa.text("'current'")
    )
    archived_at = sa.Column("catalog_archived_at", sa.DateTime(timezone=True))
    reason = sa.Column("catalog_archive_reason", sa.String(120))
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("source_definitions") as batch_op:
            batch_op.add_column(state)
            batch_op.add_column(archived_at)
            batch_op.add_column(reason)
            batch_op.create_check_constraint(
                "ck_source_definitions_catalog_state",
                "catalog_state IN ('current', 'archived')",
            )
        return
    op.add_column("source_definitions", state)
    op.add_column("source_definitions", archived_at)
    op.add_column("source_definitions", reason)
    op.create_check_constraint(
        "ck_source_definitions_catalog_state",
        "source_definitions",
        "catalog_state IN ('current', 'archived')",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("source_definitions") as batch_op:
            batch_op.drop_constraint("ck_source_definitions_catalog_state", type_="check")
            batch_op.drop_column("catalog_archive_reason")
            batch_op.drop_column("catalog_archived_at")
            batch_op.drop_column("catalog_state")
        return
    op.drop_constraint("ck_source_definitions_catalog_state", "source_definitions", type_="check")
    op.drop_column("source_definitions", "catalog_archive_reason")
    op.drop_column("source_definitions", "catalog_archived_at")
    op.drop_column("source_definitions", "catalog_state")
