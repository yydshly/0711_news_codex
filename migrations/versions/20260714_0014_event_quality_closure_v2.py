"""Preserve v1 events and add event-quality decision metadata."""

import sqlalchemy as sa
from alembic import op

revision = "20260714_0014"
down_revision = "20260713_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("visibility", sa.String(16), nullable=True))
    op.execute("UPDATE events SET visibility = 'legacy' WHERE visibility IS NULL")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("events") as batch_op:
            batch_op.alter_column(
                "visibility", nullable=False, server_default=sa.text("'current'")
            )
    else:
        op.alter_column(
            "events", "visibility", nullable=False, server_default=sa.text("'current'")
        )
    op.create_index(
        "ix_events_visibility_status_occurred_at",
        "events",
        ["visibility", "status", "occurred_at"],
    )
    op.add_column("raw_item_processing", sa.Column("outcome", sa.String(16)))
    op.add_column("raw_item_processing", sa.Column("score", sa.Integer()))
    op.add_column(
        "raw_item_processing",
        sa.Column("reason_codes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "raw_item_processing",
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("raw_item_processing", "details")
    op.drop_column("raw_item_processing", "reason_codes")
    op.drop_column("raw_item_processing", "score")
    op.drop_column("raw_item_processing", "outcome")
    op.drop_index("ix_events_visibility_status_occurred_at", table_name="events")
    op.drop_column("events", "visibility")
