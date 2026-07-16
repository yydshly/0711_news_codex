"""Persist immutable logical observation times for event heat snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "20260716_0021"
down_revision = "20260716_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("event_scores", sa.Column("observed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_event_scores_observed_at", "event_scores", ["event_id", "observed_at"])


def downgrade() -> None:
    op.drop_index("ix_event_scores_observed_at", table_name="event_scores")
    op.drop_column("event_scores", "observed_at")
