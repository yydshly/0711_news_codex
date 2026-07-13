"""Freeze remediation batches and link validation evidence."""

import sqlalchemy as sa
from alembic import op

revision = "20260713_0012"
down_revision = "20260713_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_remediation_batches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("baseline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("before_trial_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("baseline_at"),
    )
    op.create_table(
        "source_remediation_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("source_name", sa.String(length=120), nullable=False),
        sa.Column("provider_id", sa.String(length=120), nullable=False),
        sa.Column("definition_hash", sa.String(length=64), nullable=False),
        sa.Column("original_probe_id", sa.Integer(), nullable=False),
        sa.Column("original_finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("reason_zh", sa.Text(), nullable=False),
        sa.Column("next_action_zh", sa.Text(), nullable=False),
        sa.Column("access_url", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["source_remediation_batches.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["original_probe_id"], ["source_probe_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["source_definitions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "original_probe_id"),
        sa.UniqueConstraint("batch_id", "source_id"),
    )
    op.create_index(
        "ix_source_remediation_members_batch_id",
        "source_remediation_members",
        ["batch_id"],
    )
    op.add_column(
        "source_acquisition_probe_runs",
        sa.Column("operation_run_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "source_acquisition_probe_runs",
        sa.Column("original_probe_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "source_acquisition_probe_runs",
        sa.Column("retry_after_seconds", sa.Float(), nullable=True),
    )
    op.add_column(
        "source_acquisition_probe_runs",
        sa.Column("earliest_recheck_at", sa.DateTime(timezone=True), nullable=True),
    )
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_acquisition_probe_operation",
            "source_acquisition_probe_runs",
            "operation_runs",
            ["operation_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_foreign_key(
            "fk_acquisition_probe_original",
            "source_acquisition_probe_runs",
            "source_probe_runs",
            ["original_probe_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_source_acquisition_probe_runs_operation_run_id",
        "source_acquisition_probe_runs",
        ["operation_run_id"],
    )
    op.create_index(
        "ix_source_acquisition_probe_runs_original_probe_id",
        "source_acquisition_probe_runs",
        ["original_probe_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_source_acquisition_probe_runs_original_probe_id",
        table_name="source_acquisition_probe_runs",
    )
    op.drop_index(
        "ix_source_acquisition_probe_runs_operation_run_id",
        table_name="source_acquisition_probe_runs",
    )
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(
            "fk_acquisition_probe_original",
            "source_acquisition_probe_runs",
            type_="foreignkey",
        )
        op.drop_constraint(
            "fk_acquisition_probe_operation",
            "source_acquisition_probe_runs",
            type_="foreignkey",
        )
    op.drop_column("source_acquisition_probe_runs", "earliest_recheck_at")
    op.drop_column("source_acquisition_probe_runs", "retry_after_seconds")
    op.drop_column("source_acquisition_probe_runs", "original_probe_id")
    op.drop_column("source_acquisition_probe_runs", "operation_run_id")
    op.drop_index("ix_source_remediation_members_batch_id", table_name="source_remediation_members")
    op.drop_table("source_remediation_members")
    op.drop_table("source_remediation_batches")
