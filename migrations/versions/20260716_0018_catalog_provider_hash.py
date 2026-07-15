"""Freeze provider definition hashes for catalog refresh members."""

import sqlalchemy as sa
from alembic import op

revision = "20260716_0018"
down_revision = "20260715_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_catalog_refresh_members",
        sa.Column("provider_definition_hash", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_catalog_refresh_members", "provider_definition_hash")
