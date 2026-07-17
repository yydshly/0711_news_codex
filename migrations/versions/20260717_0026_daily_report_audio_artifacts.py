"""Add durable daily report audio artifacts."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0026"
down_revision = "20260717_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_report_audio_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "daily_report_id",
            sa.Integer(),
            sa.ForeignKey("daily_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rendition", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("script", sa.Text(), nullable=False),
        sa.Column("script_sha256", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("voice_id", sa.String(length=120), nullable=False),
        sa.Column("audio_format", sa.String(length=16), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("bitrate", sa.Integer(), nullable=False),
        sa.Column("channel", sa.Integer(), nullable=False),
        sa.Column(
            "operation_run_id",
            sa.Integer(),
            sa.ForeignKey("operation_runs.id", ondelete="RESTRICT"),
        ),
        sa.Column("trace_id", sa.String(length=128)),
        sa.Column("audio_duration_ms", sa.Integer()),
        sa.Column("audio_size_bytes", sa.Integer()),
        sa.Column("relative_audio_path", sa.String(length=512)),
        sa.Column("audio_sha256", sa.String(length=64)),
        sa.Column("error_code", sa.String(length=64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rendition IN ('decision', 'overview')",
            name="ck_daily_report_audio_artifact_rendition",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_daily_report_audio_artifact_status",
        ),
    )
    op.create_index(
        "ix_daily_report_audio_artifacts_report_rendition",
        "daily_report_audio_artifacts",
        ["daily_report_id", "rendition", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_daily_report_audio_artifacts_report_rendition",
        table_name="daily_report_audio_artifacts",
    )
    op.drop_table("daily_report_audio_artifacts")
