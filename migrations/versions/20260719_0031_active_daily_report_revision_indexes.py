"""Allow abandoned daily-report drafts to be replaced safely."""

import sqlalchemy as sa
from alembic import op

revision = "20260719_0031"
down_revision = "20260718_0030"
branch_labels = None
depends_on = None

IDENTITY_ACTIVE = sa.text("supersedes_report_id IS NULL AND deleted_at IS NULL")
SUCCESSOR_ACTIVE = sa.text(
    "supersedes_report_id IS NOT NULL AND deleted_at IS NULL"
)


def upgrade() -> None:
    op.drop_index(
        "uq_daily_report_supersedes", table_name="daily_reports", if_exists=True
    )
    op.drop_index("uq_daily_report_identity", table_name="daily_reports", if_exists=True)
    op.create_index(
        "uq_daily_report_identity",
        "daily_reports",
        ["report_date", "window_hours", "source_operation_id"],
        unique=True,
        postgresql_where=IDENTITY_ACTIVE,
        sqlite_where=IDENTITY_ACTIVE,
    )
    op.create_index(
        "uq_daily_report_supersedes",
        "daily_reports",
        ["supersedes_report_id"],
        unique=True,
        postgresql_where=SUCCESSOR_ACTIVE,
        sqlite_where=SUCCESSOR_ACTIVE,
    )


def downgrade() -> None:
    bind = op.get_bind()
    successor_duplicate = bind.execute(
        sa.text(
            "SELECT supersedes_report_id FROM daily_reports "
            "WHERE supersedes_report_id IS NOT NULL "
            "GROUP BY supersedes_report_id HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    root_duplicate = bind.execute(
        sa.text(
            "SELECT report_date, window_hours, source_operation_id FROM daily_reports "
            "WHERE supersedes_report_id IS NULL "
            "GROUP BY report_date, window_hours, source_operation_id "
            "HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if successor_duplicate is not None or root_duplicate is not None:
        raise RuntimeError("cannot restore unconditional daily-report identity uniqueness")

    op.drop_index(
        "uq_daily_report_supersedes", table_name="daily_reports", if_exists=True
    )
    op.drop_index("uq_daily_report_identity", table_name="daily_reports", if_exists=True)
    op.create_index(
        "uq_daily_report_identity",
        "daily_reports",
        ["report_date", "window_hours", "source_operation_id"],
        unique=True,
        postgresql_where=sa.text("supersedes_report_id IS NULL"),
        sqlite_where=sa.text("supersedes_report_id IS NULL"),
    )
    op.create_index(
        "uq_daily_report_supersedes",
        "daily_reports",
        ["supersedes_report_id"],
        unique=True,
    )
