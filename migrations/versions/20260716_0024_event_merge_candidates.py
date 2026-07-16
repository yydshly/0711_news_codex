"""Add the immutable event merge candidate ledger."""

import sqlalchemy as sa
from alembic import op

revision = "20260716_0024"
down_revision = "20260716_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_merge_candidates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supersedes_candidate_id", sa.Integer()),
        sa.Column("left_event_id", sa.Integer(), nullable=False),
        sa.Column("left_version_number", sa.Integer(), nullable=False),
        sa.Column("right_event_id", sa.Integer(), nullable=False),
        sa.Column("right_version_number", sa.Integer(), nullable=False),
        sa.Column("candidate_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("algorithm_version", sa.String(length=120), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("facts_snapshot", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("zh_reason", sa.Text(), nullable=False),
        sa.Column("zh_next_action", sa.Text(), nullable=False),
        sa.Column(
            "generated_operation_id",
            sa.Integer(),
            sa.ForeignKey("operation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "reviewed_operation_id",
            sa.Integer(),
            sa.ForeignKey("operation_runs.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "applied_operation_id",
            sa.Integer(),
            sa.ForeignKey("operation_runs.id", ondelete="RESTRICT"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("result_summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["supersedes_candidate_id"],
            ["event_merge_candidates.id"],
            name="fk_event_merge_supersedes",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["left_event_id", "left_version_number"],
            ["event_versions.event_id", "event_versions.version_number"],
            name="fk_event_merge_left_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["right_event_id", "right_version_number"],
            ["event_versions.event_id", "event_versions.version_number"],
            name="fk_event_merge_right_version",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_event_merge_candidate_revision"
        ),
        sa.CheckConstraint(
            "left_event_id < right_event_id", name="ck_event_merge_pair_order"
        ),
        sa.CheckConstraint(
            "left_version_number > 0", name="ck_event_merge_left_version"
        ),
        sa.CheckConstraint(
            "right_version_number > 0", name="ck_event_merge_right_version"
        ),
        sa.CheckConstraint(
            "candidate_type IN ('legacy_identity','deterministic_merge','manual_review')",
            name="ck_event_merge_candidate_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending','confirmed','dismissed','applied','expired','failed')",
            name="ck_event_merge_candidate_status",
        ),
        sa.UniqueConstraint(
            "left_event_id",
            "left_version_number",
            "right_event_id",
            "right_version_number",
            "algorithm_version",
            "input_fingerprint",
            "revision",
            name="uq_event_merge_candidate_input",
        ),
        sa.UniqueConstraint(
            "supersedes_candidate_id",
            name="uq_event_merge_candidate_supersedes",
        ),
    )
    op.create_index(
        "uq_event_merge_candidate_root",
        "event_merge_candidates",
        [
            "left_event_id",
            "left_version_number",
            "right_event_id",
            "right_version_number",
            "algorithm_version",
        ],
        unique=True,
        sqlite_where=sa.text("supersedes_candidate_id IS NULL"),
        postgresql_where=sa.text("supersedes_candidate_id IS NULL"),
    )
    op.create_index(
        "ix_event_merge_candidates_status_type",
        "event_merge_candidates",
        ["status", "candidate_type", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_event_merge_candidates_status_type", table_name="event_merge_candidates"
    )
    op.drop_index(
        "uq_event_merge_candidate_root", table_name="event_merge_candidates"
    )
    op.drop_table("event_merge_candidates")
