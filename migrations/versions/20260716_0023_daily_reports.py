"""Add immutable manual Chinese daily report archives."""

import sqlalchemy as sa
from alembic import op

revision = "20260716_0023"
down_revision = "20260716_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source_operation_id",
            sa.Integer(),
            sa.ForeignKey("operation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "supersedes_report_id",
            sa.Integer(),
            sa.ForeignKey("daily_reports.id", ondelete="RESTRICT"),
        ),
        sa.Column("generation_summary", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("window_hours IN (24, 48, 72)", name="ck_daily_report_window"),
        sa.CheckConstraint("status IN ('draft', 'archived')", name="ck_daily_report_status"),
        sa.CheckConstraint("revision > 0", name="ck_daily_report_revision"),
        sa.UniqueConstraint(
            "report_date", "window_hours", "revision", name="uq_daily_report_revision"
        ),
    )
    op.create_index(
        "ix_daily_reports_date_status", "daily_reports", ["report_date", "status"]
    )
    op.create_table(
        "daily_report_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "daily_report_id",
            sa.Integer(),
            sa.ForeignKey("daily_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_version_number", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "section IN ('confirmed', 'emerging')", name="ck_daily_report_item_section"
        ),
        sa.CheckConstraint("position > 0", name="ck_daily_report_item_position"),
        sa.UniqueConstraint(
            "daily_report_id",
            "event_id",
            "event_version_number",
            name="uq_daily_report_event_version",
        ),
        sa.UniqueConstraint(
            "daily_report_id", "section", "position", name="uq_daily_report_position"
        ),
    )
    op.create_index(
        "ix_daily_report_items_report_section",
        "daily_report_items",
        ["daily_report_id", "section", "position"],
    )


def downgrade() -> None:
    op.drop_index("ix_daily_report_items_report_section", table_name="daily_report_items")
    op.drop_table("daily_report_items")
    op.drop_index("ix_daily_reports_date_status", table_name="daily_reports")
    op.drop_table("daily_reports")
