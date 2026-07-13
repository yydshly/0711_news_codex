"""Persist source-research current projections and probe history."""

import sqlalchemy as sa
from alembic import op

revision = "20260712_0009"
down_revision = "20260712_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_research_profiles",
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("wanted_information", sa.JSON(), nullable=False),
        sa.Column("conclusion", sa.Text(), nullable=True),
        sa.Column("no_fallback_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["source_definitions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id"),
    )
    op.create_table(
        "source_acquisition_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("candidate_key", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("implementation", sa.String(length=64), nullable=False),
        sa.Column("officiality", sa.String(length=32), nullable=False),
        sa.Column("authentication", sa.String(length=32), nullable=False),
        sa.Column("roles", sa.JSON(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("sample_status", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reviewed_at", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["source_definitions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "candidate_key"),
    )
    op.create_index(
        "ix_source_acquisition_candidates_source_id",
        "source_acquisition_candidates",
        ["source_id"],
        unique=False,
    )
    op.create_table(
        "source_acquisition_probe_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("fields_present", sa.JSON(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=True),
        sa.Column("latest_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["source_acquisition_candidates.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_source_acquisition_probe_runs_candidate_id",
        "source_acquisition_probe_runs",
        ["candidate_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_source_acquisition_probe_runs_candidate_id", "source_acquisition_probe_runs")
    op.drop_table("source_acquisition_probe_runs")
    op.drop_index("ix_source_acquisition_candidates_source_id", "source_acquisition_candidates")
    op.drop_table("source_acquisition_candidates")
    op.drop_table("source_research_profiles")
