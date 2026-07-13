"""Retain retired acquisition candidates for probe history."""

import sqlalchemy as sa
from alembic import op

revision = "20260712_0010"
down_revision = "20260712_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_acquisition_candidates",
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "source_acquisition_candidates",
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_source_acquisition_candidates_current",
        "source_acquisition_candidates",
        ["source_id", "is_current"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_source_acquisition_candidates_current", "source_acquisition_candidates")
    op.drop_column("source_acquisition_candidates", "removed_at")
    op.drop_column("source_acquisition_candidates", "is_current")
