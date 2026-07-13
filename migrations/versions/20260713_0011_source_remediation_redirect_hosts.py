"""Persist audited HTML selectors and redirect hosts."""

import sqlalchemy as sa
from alembic import op

revision = "20260713_0011"
down_revision = "20260712_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_acquisition_candidates", sa.Column("selector", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "source_acquisition_candidates",
        sa.Column("allowed_redirect_hosts", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("source_acquisition_candidates", "allowed_redirect_hosts")
    op.drop_column("source_acquisition_candidates", "selector")
