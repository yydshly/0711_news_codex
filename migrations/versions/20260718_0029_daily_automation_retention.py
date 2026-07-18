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
        sa.Column("last_retention_date", sa.Date()),
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
    _allow_archived_report_retention_mutations()


def downgrade() -> None:
    _restore_strict_archived_report_guards()
    op.drop_index("ix_daily_reports_pinned_date", table_name="daily_reports")
    op.drop_index("ix_daily_reports_deleted_purge", table_name="daily_reports")
    op.drop_column("daily_reports", "purge_after")
    op.drop_column("daily_reports", "deleted_at")
    op.drop_column("daily_reports", "pinned_at")
    op.drop_index("ix_daily_automation_next_run", table_name="daily_automation_config")
    op.drop_table("daily_automation_config")


def _allow_archived_report_retention_mutations() -> None:
    if op.get_bind().dialect.name == "sqlite":
        if not _sqlite_archived_report_guards_exist():
            return
        op.execute("DROP TRIGGER IF EXISTS trg_daily_report_archived_update")
        op.execute("DROP TRIGGER IF EXISTS trg_daily_report_archived_delete")
        op.execute(
            """
            CREATE TRIGGER trg_daily_report_archived_update
            BEFORE UPDATE ON daily_reports
            FOR EACH ROW WHEN OLD.status = 'archived' AND (
                NEW.id IS NOT OLD.id OR
                NEW.report_date IS NOT OLD.report_date OR
                NEW.timezone IS NOT OLD.timezone OR
                NEW.window_hours IS NOT OLD.window_hours OR
                NEW.window_start IS NOT OLD.window_start OR
                NEW.window_end IS NOT OLD.window_end OR
                NEW.source_operation_id IS NOT OLD.source_operation_id OR
                NEW.status IS NOT OLD.status OR
                NEW.revision IS NOT OLD.revision OR
                NEW.supersedes_report_id IS NOT OLD.supersedes_report_id OR
                NEW.generation_summary IS NOT OLD.generation_summary OR
                NEW.generated_at IS NOT OLD.generated_at OR
                NEW.archived_at IS NOT OLD.archived_at
            )
            BEGIN
                SELECT RAISE(ABORT, 'daily_report_archived_immutable');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_daily_report_archived_delete
            BEFORE DELETE ON daily_reports
            FOR EACH ROW WHEN OLD.status = 'archived' AND OLD.deleted_at IS NULL
            BEGIN
                SELECT RAISE(ABORT, 'daily_report_archived_immutable');
            END
            """
        )
        return

    op.execute(
        """
        CREATE OR REPLACE FUNCTION newsradar_guard_archived_daily_report()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status = 'archived' THEN
                IF TG_OP = 'DELETE' THEN
                    IF OLD.deleted_at IS NULL THEN
                        RAISE EXCEPTION 'daily_report_archived_immutable'
                            USING ERRCODE = '23514';
                    END IF;
                    RETURN OLD;
                END IF;
                IF ROW(
                    NEW.id, NEW.report_date, NEW.timezone, NEW.window_hours,
                    NEW.window_start, NEW.window_end, NEW.source_operation_id,
                    NEW.status, NEW.revision, NEW.supersedes_report_id,
                    NEW.generation_summary, NEW.generated_at, NEW.archived_at
                ) IS DISTINCT FROM ROW(
                    OLD.id, OLD.report_date, OLD.timezone, OLD.window_hours,
                    OLD.window_start, OLD.window_end, OLD.source_operation_id,
                    OLD.status, OLD.revision, OLD.supersedes_report_id,
                    OLD.generation_summary, OLD.generated_at, OLD.archived_at
                ) THEN
                    RAISE EXCEPTION 'daily_report_archived_immutable'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )


def _restore_strict_archived_report_guards() -> None:
    if op.get_bind().dialect.name == "sqlite":
        if not _sqlite_archived_report_guards_exist():
            return
        op.execute("DROP TRIGGER IF EXISTS trg_daily_report_archived_update")
        op.execute("DROP TRIGGER IF EXISTS trg_daily_report_archived_delete")
        op.execute(
            """
            CREATE TRIGGER trg_daily_report_archived_update
            BEFORE UPDATE ON daily_reports
            FOR EACH ROW WHEN OLD.status = 'archived'
            BEGIN
                SELECT RAISE(ABORT, 'daily_report_archived_immutable');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_daily_report_archived_delete
            BEFORE DELETE ON daily_reports
            FOR EACH ROW WHEN OLD.status = 'archived'
            BEGIN
                SELECT RAISE(ABORT, 'daily_report_archived_immutable');
            END
            """
        )
        return

    op.execute(
        """
        CREATE OR REPLACE FUNCTION newsradar_guard_archived_daily_report()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status = 'archived' THEN
                RAISE EXCEPTION 'daily_report_archived_immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )


def _sqlite_archived_report_guards_exist() -> bool:
    return bool(
        op.get_bind().scalar(
            sa.text(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'trigger' AND name = 'trg_daily_report_archived_update'"
            )
        )
    )
