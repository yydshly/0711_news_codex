"""Add durable daily autopilot runs."""

import sqlalchemy as sa
from alembic import op

revision = "20260718_0028"
down_revision = "20260717_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_autopilot_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=48), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False),
        sa.Column("requested_scope", sa.JSON(), nullable=False),
        sa.Column(
            "source_operation_id",
            sa.Integer(),
            sa.ForeignKey("operation_runs.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "event_operation_id",
            sa.Integer(),
            sa.ForeignKey("operation_runs.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "decision_audio_operation_id",
            sa.Integer(),
            sa.ForeignKey("operation_runs.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "overview_audio_operation_id",
            sa.Integer(),
            sa.ForeignKey("operation_runs.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "daily_report_id",
            sa.Integer(),
            sa.ForeignKey("daily_reports.id", ondelete="RESTRICT"),
        ),
        sa.Column("result_summary", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=96)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "window_hours IN (24, 48, 72)", name="ck_daily_autopilot_window"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_daily_autopilot_status",
        ),
    )
    op.create_index(
        "ix_daily_autopilot_runs_created_at", "daily_autopilot_runs", ["created_at"]
    )
    op.create_index(
        "ix_daily_autopilot_runs_source_operation",
        "daily_autopilot_runs",
        ["source_operation_id"],
    )
    op.create_index(
        "ix_daily_autopilot_runs_event_operation",
        "daily_autopilot_runs",
        ["event_operation_id"],
    )
    op.create_index(
        "ix_daily_autopilot_runs_decision_audio",
        "daily_autopilot_runs",
        ["decision_audio_operation_id"],
    )
    op.create_index(
        "ix_daily_autopilot_runs_overview_audio",
        "daily_autopilot_runs",
        ["overview_audio_operation_id"],
    )
    op.create_index(
        "ix_daily_autopilot_runs_daily_report",
        "daily_autopilot_runs",
        ["daily_report_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_daily_autopilot_runs_daily_report", table_name="daily_autopilot_runs")
    op.drop_index("ix_daily_autopilot_runs_overview_audio", table_name="daily_autopilot_runs")
    op.drop_index("ix_daily_autopilot_runs_decision_audio", table_name="daily_autopilot_runs")
    op.drop_index("ix_daily_autopilot_runs_event_operation", table_name="daily_autopilot_runs")
    op.drop_index("ix_daily_autopilot_runs_source_operation", table_name="daily_autopilot_runs")
    op.drop_index("ix_daily_autopilot_runs_created_at", table_name="daily_autopilot_runs")
    op.drop_table("daily_autopilot_runs")
