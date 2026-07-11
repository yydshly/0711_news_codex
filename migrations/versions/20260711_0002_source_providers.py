"""Add provider registry and target coverage metadata."""

import sqlalchemy as sa
from alembic import op

revision = "20260711_0002"
down_revision = "20260711_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_providers",
        sa.Column("id", sa.String(120), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("homepage", sa.Text(), nullable=False),
        sa.Column("docs_url", sa.Text(), nullable=False),
        sa.Column("terms_url", sa.Text(), nullable=False),
        sa.Column("auth_mode", sa.String(32), nullable=False),
        sa.Column("cost_tier", sa.String(32), nullable=False),
        sa.Column("availability", sa.String(32), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("required_env", sa.JSON(), nullable=False),
        sa.Column("reviewed_at", sa.Date(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("unlock_requirements", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "source_provider_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "provider_id", sa.String(120), sa.ForeignKey("source_providers.id"), nullable=False
        ),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider_id", "definition_hash"),
    )
    op.create_table(
        "source_provider_probe_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "provider_id", sa.String(120), sa.ForeignKey("source_providers.id"), nullable=False
        ),
        sa.Column("probe_type", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("availability", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("http_status", sa.Integer()),
        sa.Column("evidence_url", sa.Text(), nullable=False),
    )
    op.add_column(
        "source_definitions",
        sa.Column("provider_id", sa.String(120), nullable=False, server_default="independent"),
    )
    op.add_column(
        "source_definitions",
        sa.Column("target_type", sa.String(32), nullable=False, server_default="publisher_feed"),
    )
    op.add_column(
        "source_definitions",
        sa.Column("availability", sa.String(32), nullable=False, server_default="ready"),
    )
    op.add_column(
        "source_definitions",
        sa.Column("coverage_mode", sa.String(32), nullable=False, server_default="direct"),
    )
    op.add_column("source_definitions", sa.Column("official_identity_url", sa.Text()))
    op.add_column("source_definitions", sa.Column("reviewed_at", sa.Date()))
    op.add_column(
        "source_definitions",
        sa.Column("unlock_requirements", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    for column in (
        "unlock_requirements",
        "reviewed_at",
        "official_identity_url",
        "coverage_mode",
        "availability",
        "target_type",
        "provider_id",
    ):
        op.drop_column("source_definitions", column)
    op.drop_table("source_provider_probe_runs")
    op.drop_table("source_provider_versions")
    op.drop_table("source_providers")
