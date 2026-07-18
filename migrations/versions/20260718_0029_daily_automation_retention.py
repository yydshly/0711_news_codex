"""Add daily automation and report retention schema."""

import sqlalchemy as sa
from alembic import op

revision = "20260718_0029"
down_revision = "20260718_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_automation_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("daily_time", sa.String(length=5), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("resource_profile", sa.String(length=16), nullable=False),
        sa.Column("last_scheduled_date", sa.Date()),
        sa.Column(
            "last_run_id",
            sa.Integer(),
            sa.ForeignKey("daily_autopilot_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_daily_automation_singleton"),
        sa.CheckConstraint("window_hours = 24", name="ck_daily_automation_window"),
        sa.CheckConstraint(
            "resource_profile IN ('standard', 'power_saver')",
            name="ck_daily_automation_resource_profile",
        ),
    )
    op.create_index(
        "ix_daily_automation_next_run",
        "daily_automation_config",
        ["enabled", "next_run_at"],
    )
    op.add_column("daily_reports", sa.Column("pinned_at", sa.DateTime(timezone=True)))
    op.add_column("daily_reports", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("daily_reports", sa.Column("purge_after", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_daily_reports_deleted_purge", "daily_reports", ["deleted_at", "purge_after"]
    )
    op.create_index(
        "ix_daily_reports_pinned_date", "daily_reports", ["pinned_at", "report_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_daily_reports_pinned_date", table_name="daily_reports")
    op.drop_index("ix_daily_reports_deleted_purge", table_name="daily_reports")
    op.drop_column("daily_reports", "purge_after")
    op.drop_column("daily_reports", "deleted_at")
    op.drop_column("daily_reports", "pinned_at")
    op.drop_index("ix_daily_automation_next_run", table_name="daily_automation_config")
    op.drop_table("daily_automation_config")
