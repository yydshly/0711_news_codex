"""Create the immutable phase-one source intelligence registry schema."""

import sqlalchemy as sa
from alembic import op

revision = "20260711_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_definitions",
        sa.Column("id", sa.String(120), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("nature", sa.String(32), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("roles", sa.JSON(), nullable=False),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.Column("authority_score", sa.Integer(), nullable=False),
        sa.Column("poll_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("expected_fields", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "source_definition_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id", sa.String(120), sa.ForeignKey("source_definitions.id"), nullable=False
        ),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "definition_hash"),
    )
    op.create_table(
        "source_access_methods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id", sa.String(120), sa.ForeignKey("source_definitions.id"), nullable=False
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("requires_manual_approval", sa.Boolean(), nullable=False),
        sa.Column("auth_env", sa.String(120)),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.UniqueConstraint("source_id", "priority"),
    )
    op.create_table(
        "source_risk_assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id", sa.String(120), sa.ForeignKey("source_definitions.id"), nullable=False
        ),
        sa.Column("terms", sa.Integer(), nullable=False),
        sa.Column("authentication", sa.Integer(), nullable=False),
        sa.Column("stability", sa.Integer(), nullable=False),
        sa.Column("data_quality", sa.Integer(), nullable=False),
        sa.Column("operating_cost", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("hard_block_reason", sa.Text()),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "source_probe_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id", sa.String(120), sa.ForeignKey("source_definitions.id"), nullable=False
        ),
        sa.Column("access_kind", sa.String(32), nullable=False),
        sa.Column("access_url", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("http_status", sa.Integer()),
        sa.Column("final_url", sa.Text()),
        sa.Column("response_headers", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("schema_fingerprint", sa.String(64)),
        sa.Column("suggested_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(64)),
    )
    op.create_table(
        "source_probe_samples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "probe_run_id", sa.Integer(), sa.ForeignKey("source_probe_runs.id"), nullable=False
        ),
        sa.Column("sample_index", sa.Integer(), nullable=False),
        sa.Column("canonical_url", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("fields_present", sa.JSON(), nullable=False),
        sa.Column("sample_hash", sa.String(64), nullable=False),
    )
    op.create_table(
        "fetch_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id", sa.String(120), sa.ForeignKey("source_definitions.id"), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
    )
    op.create_table(
        "raw_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id", sa.String(120), sa.ForeignKey("source_definitions.id"), nullable=False
        ),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "external_id"),
    )
    op.create_table(
        "model_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "model_usage",
        "raw_items",
        "fetch_runs",
        "source_probe_samples",
        "source_probe_runs",
        "source_risk_assessments",
        "source_access_methods",
        "source_definition_versions",
        "source_definitions",
    ):
        op.drop_table(table)
