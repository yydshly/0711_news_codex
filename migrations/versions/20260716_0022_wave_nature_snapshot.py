"""Freeze source nature for auditable high-value wave evidence."""

import sqlalchemy as sa
from alembic import op

revision = "20260716_0022"
down_revision = "20260716_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing wave members predate this field.  Conservatively treating them as
    # community prevents accidental confirmation if an old operation is replayed.
    op.add_column(
        "high_value_wave_members",
        sa.Column(
            "nature_snapshot",
            sa.String(length=32),
            nullable=False,
            server_default="community",
        ),
    )


def downgrade() -> None:
    op.drop_column("high_value_wave_members", "nature_snapshot")
