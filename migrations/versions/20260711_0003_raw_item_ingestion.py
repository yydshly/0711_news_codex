"""Add durable raw-item ingestion runtime data."""

import sqlalchemy as sa
from alembic import op

revision = "20260711_0003"
down_revision = "20260711_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workers",
        sa.Column("worker_id", sa.String(120), primary_key=True),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("process_id", sa.Integer()),
        sa.Column("version", sa.String(120)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_operation_run_id", sa.Integer()),
    )
    op.create_table(
        "operation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operation_type", sa.String(32), nullable=False),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("requested_scope", sa.JSON(), nullable=False),
        sa.Column("progress_current", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer()),
        sa.Column("result_summary", sa.JSON(), nullable=False),
        sa.Column("worker_id", sa.String(120), sa.ForeignKey("workers.worker_id")),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_operation_runs_queue", "operation_runs", ["status", "next_attempt_at"])
    op.create_index("ix_operation_runs_lease_expires_at", "operation_runs", ["lease_expires_at"])
    op.create_table(
        "operation_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "operation_run_id", sa.Integer(), sa.ForeignKey("operation_runs.id"), nullable=False
        ),
        sa.Column("worker_id", sa.String(120), sa.ForeignKey("workers.worker_id"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.UniqueConstraint("operation_run_id", "attempt_number"),
    )
    op.create_table(
        "operation_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "operation_run_id", sa.Integer(), sa.ForeignKey("operation_runs.id"), nullable=False
        ),
        sa.Column("attempt_id", sa.Integer(), sa.ForeignKey("operation_attempts.id")),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("phase", sa.String(64)),
        sa.Column("source_id", sa.String(120), sa.ForeignKey("source_definitions.id")),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    for name, type_ in (
        ("operation_run_id", sa.Integer()),
        ("operation_attempt_id", sa.Integer()),
        ("access_method_id", sa.Integer()),
        ("http_status", sa.Integer()),
        ("final_url", sa.Text()),
        ("etag", sa.String(512)),
        ("last_modified", sa.String(512)),
        ("items_received", sa.Integer()),
        ("items_inserted", sa.Integer()),
        ("items_updated", sa.Integer()),
        ("items_unchanged", sa.Integer()),
        ("items_skipped", sa.Integer()),
        ("items_failed", sa.Integer()),
        ("next_cursor", sa.Text()),
        ("error_code", sa.String(64)),
        ("error_message", sa.Text()),
    ):
        op.add_column("fetch_runs", sa.Column(name, type_))

    for name, type_ in (
        ("original_url", sa.Text()), ("title", sa.Text()), ("authors", sa.JSON()),
        ("summary", sa.Text()), ("content", sa.Text()), ("language", sa.String(16)),
        ("content_type", sa.String(64)), ("source_updated_at", sa.DateTime(timezone=True)),
        ("discussion_url", sa.Text()), ("engagement", sa.JSON()), ("item_kind", sa.String(64)),
        ("publisher_name", sa.String(255)), ("publisher_url", sa.Text()),
        ("discovery_url", sa.Text()), ("origin_resolution_status", sa.String(32)),
        ("author_account_id", sa.String(255)), ("author_handle", sa.String(255)),
        ("thread_root_id", sa.String(255)), ("raw_payload", sa.JSON()),
        ("content_hash", sa.String(64)), ("title_fingerprint", sa.String(64)),
        ("canonical_url_hash", sa.String(64)), ("first_seen_run_id", sa.Integer()),
        ("last_seen_run_id", sa.Integer()), ("first_seen_at", sa.DateTime(timezone=True)),
        ("last_seen_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("raw_items", sa.Column(name, type_))
    op.create_index("ix_raw_items_source_published_at", "raw_items", ["source_id", "published_at"])
    op.create_index("ix_raw_items_canonical_url_hash", "raw_items", ["canonical_url_hash"])
    op.create_index("ix_raw_items_title_fingerprint", "raw_items", ["title_fingerprint"])

    op.create_table(
        "raw_item_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("raw_item_id", sa.Integer(), sa.ForeignKey("raw_items.id"), nullable=False),
        sa.Column("fetch_run_id", sa.Integer(), sa.ForeignKey("fetch_runs.id")),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("raw_item_id", "content_hash"),
    )
    op.create_table(
        "fetch_run_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fetch_run_id", sa.Integer(), sa.ForeignKey("fetch_runs.id"), nullable=False),
        sa.Column("raw_item_id", sa.Integer(), sa.ForeignKey("raw_items.id")),
        sa.Column("external_id", sa.String(255)),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "duplicate_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("raw_item_id", sa.Integer(), sa.ForeignKey("raw_items.id"), nullable=False),
        sa.Column(
            "candidate_raw_item_id", sa.Integer(), sa.ForeignKey("raw_items.id"), nullable=False
        ),
        sa.Column("match_type", sa.String(32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("raw_item_id", "candidate_raw_item_id", "match_type"),
    )
    op.create_table(
        "source_fetch_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id", sa.String(120), sa.ForeignKey("source_definitions.id"), nullable=False
        ),
        sa.Column(
            "access_method_id",
            sa.Integer(),
            sa.ForeignKey("source_access_methods.id"),
            nullable=False,
        ),
        sa.Column("etag", sa.String(512)),
        sa.Column("last_modified", sa.String(512)),
        sa.Column("cursor", sa.Text()),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "access_method_id"),
    )


def downgrade() -> None:
    op.drop_table("source_fetch_states")
    op.drop_table("duplicate_candidates")
    op.drop_table("fetch_run_items")
    op.drop_table("raw_item_snapshots")
    op.drop_index("ix_raw_items_title_fingerprint", table_name="raw_items")
    op.drop_index("ix_raw_items_canonical_url_hash", table_name="raw_items")
    op.drop_index("ix_raw_items_source_published_at", table_name="raw_items")
    for column in (
        "last_seen_at", "first_seen_at", "last_seen_run_id", "first_seen_run_id",
        "canonical_url_hash", "title_fingerprint", "content_hash", "raw_payload",
        "thread_root_id", "author_handle", "author_account_id", "origin_resolution_status",
        "discovery_url", "publisher_url", "publisher_name", "item_kind", "engagement",
        "discussion_url", "source_updated_at", "content_type", "language", "content",
        "summary", "authors", "title", "original_url",
    ):
        op.drop_column("raw_items", column)
    for column in (
        "error_message", "error_code", "next_cursor", "items_failed", "items_skipped",
        "items_unchanged", "items_updated", "items_inserted", "items_received",
        "last_modified", "etag", "final_url", "http_status", "access_method_id",
        "operation_attempt_id", "operation_run_id",
    ):
        op.drop_column("fetch_runs", column)
    op.drop_table("operation_events")
    op.drop_table("operation_attempts")
    op.drop_index("ix_operation_runs_lease_expires_at", table_name="operation_runs")
    op.drop_index("ix_operation_runs_queue", table_name="operation_runs")
    op.drop_table("operation_runs")
    op.drop_table("workers")
