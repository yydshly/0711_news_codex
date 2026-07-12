"""Add durable event-intelligence persistence."""

import sqlalchemy as sa
from alembic import op

revision = "20260712_0007"
down_revision = "20260712_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_item_processing",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("raw_item_id", sa.Integer(), sa.ForeignKey("raw_items.id"), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("algorithm_version", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("raw_item_id", "stage", "algorithm_version"),
    )
    op.create_table(
        "event_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_key", sa.String(255), nullable=False),
        sa.Column("algorithm_version", sa.String(120), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(32)),
        sa.Column("state", sa.String(32), nullable=False, server_default="active"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("candidate_key", "algorithm_version"),
    )
    op.create_index("ix_event_candidates_state", "event_candidates", ["state", "updated_at"])
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_key", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("category", sa.String(32)),
        sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("lease_operation_id", sa.Integer(), sa.ForeignKey("operation_runs.id")),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_events_status_occurred_at", "events", ["status", "occurred_at"])
    op.create_table(
        "event_candidate_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "candidate_id", sa.Integer(), sa.ForeignKey("event_candidates.id"), nullable=False
        ),
        sa.Column("raw_item_id", sa.Integer(), sa.ForeignKey("raw_items.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("candidate_id", "raw_item_id"),
    )
    op.create_index(
        "ix_event_candidate_items_active", "event_candidate_items", ["candidate_id", "raw_item_id"]
    )
    op.create_table(
        "event_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("zh_title", sa.Text()),
        sa.Column("zh_summary", sa.Text()),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", "version_number"),
    )
    op.create_table(
        "event_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("raw_item_id", sa.Integer(), sa.ForeignKey("raw_items.id"), nullable=False),
        sa.Column("added_version_number", sa.Integer(), nullable=False),
        sa.Column("removed_version_number", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", "raw_item_id", "added_version_number"),
    )
    op.create_index(
        "ix_event_items_active_membership",
        "event_items",
        ["event_id", "removed_version_number", "raw_item_id"],
    )
    op.create_table(
        "entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_key", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("canonical_key", "entity_type"),
    )
    op.create_table(
        "event_entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", "entity_id"),
    )
    op.create_table(
        "event_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("heat", sa.Float(), nullable=False),
        sa.Column("breakdown", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_event_scores_ranking", "event_scores", ["heat", "event_id"])
    op.create_table(
        "event_model_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id")),
        sa.Column("raw_item_id", sa.Integer(), sa.ForeignKey("raw_items.id")),
        sa.Column("model_usage_id", sa.Integer(), sa.ForeignKey("model_usage.id")),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("algorithm_version", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("event_model_runs")
    op.drop_index("ix_event_scores_ranking", table_name="event_scores")
    op.drop_table("event_scores")
    op.drop_table("event_entities")
    op.drop_table("entities")
    op.execute("DROP INDEX IF EXISTS ix_event_items_active_membership")
    op.drop_table("event_items")
    op.drop_table("event_versions")
    op.drop_index("ix_event_candidate_items_active", table_name="event_candidate_items")
    op.drop_table("event_candidate_items")
    op.drop_index("ix_events_status_occurred_at", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_event_candidates_state", table_name="event_candidates")
    op.drop_table("event_candidates")
    op.drop_table("raw_item_processing")
