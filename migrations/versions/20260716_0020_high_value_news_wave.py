"""Persist frozen high-value news wave members."""

import sqlalchemy as sa
from alembic import op

revision = "20260716_0020"
down_revision = "20260716_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "high_value_wave_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("operation_run_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("provider_id", sa.String(length=120), nullable=False),
        sa.Column("definition_hash", sa.String(length=64), nullable=False),
        sa.Column("roles_snapshot", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("availability_snapshot", sa.String(length=32), nullable=False),
        sa.Column("access_kind_snapshot", sa.String(length=32), nullable=False),
        sa.Column("fetchable", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("fetch_run_id", sa.Integer()),
        sa.Column("result_code", sa.String(length=64)),
        sa.Column("conclusion", sa.Text()),
        sa.Column("claim_attempt_id", sa.Integer()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["operation_run_id"], ["operation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["source_definitions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["fetch_run_id"], ["fetch_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["claim_attempt_id"], ["operation_attempts.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("operation_run_id", "source_id"),
    )
    op.create_index(
        "ix_high_value_wave_member_state", "high_value_wave_members", ["operation_run_id", "state"]
    )


def downgrade() -> None:
    op.drop_index("ix_high_value_wave_member_state", table_name="high_value_wave_members")
    op.drop_table("high_value_wave_members")
