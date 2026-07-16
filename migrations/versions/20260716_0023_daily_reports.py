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
        sa.CheckConstraint(
            "(status = 'draft' AND archived_at IS NULL) OR "
            "(status = 'archived' AND archived_at IS NOT NULL)",
            name="ck_daily_report_archive_state",
        ),
        sa.CheckConstraint("revision > 0", name="ck_daily_report_revision"),
        sa.UniqueConstraint(
            "report_date", "window_hours", "revision", name="uq_daily_report_revision"
        ),
    )
    op.create_index(
        "ix_daily_reports_date_status", "daily_reports", ["report_date", "status"]
    )
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
    if op.get_bind().dialect.name == "sqlite":
        _create_sqlite_archive_guards()
    else:
        _create_postgresql_archive_guards()


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _drop_sqlite_archive_guards()
    else:
        _drop_postgresql_archive_guards()
    op.drop_index("ix_daily_report_items_report_section", table_name="daily_report_items")
    op.drop_table("daily_report_items")
    op.drop_index(
        "uq_daily_report_supersedes", table_name="daily_reports", if_exists=True
    )
    op.drop_index("uq_daily_report_identity", table_name="daily_reports", if_exists=True)
    op.drop_index("ix_daily_reports_date_status", table_name="daily_reports")
    op.drop_table("daily_reports")


def _create_sqlite_archive_guards() -> None:
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
    op.execute(
        """
        CREATE TRIGGER trg_daily_report_item_archived_insert
        BEFORE INSERT ON daily_report_items
        FOR EACH ROW WHEN EXISTS (
            SELECT 1 FROM daily_reports
            WHERE id = NEW.daily_report_id AND status = 'archived'
        )
        BEGIN
            SELECT RAISE(ABORT, 'daily_report_archived_immutable');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_daily_report_item_archived_update
        BEFORE UPDATE ON daily_report_items
        FOR EACH ROW WHEN EXISTS (
            SELECT 1 FROM daily_reports
            WHERE id IN (OLD.daily_report_id, NEW.daily_report_id) AND status = 'archived'
        )
        BEGIN
            SELECT RAISE(ABORT, 'daily_report_archived_immutable');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_daily_report_item_archived_delete
        BEFORE DELETE ON daily_report_items
        FOR EACH ROW WHEN EXISTS (
            SELECT 1 FROM daily_reports
            WHERE id = OLD.daily_report_id AND status = 'archived'
        )
        BEGIN
            SELECT RAISE(ABORT, 'daily_report_archived_immutable');
        END
        """
    )


def _drop_sqlite_archive_guards() -> None:
    for trigger_name in (
        "trg_daily_report_item_archived_delete",
        "trg_daily_report_item_archived_update",
        "trg_daily_report_item_archived_insert",
        "trg_daily_report_archived_delete",
        "trg_daily_report_archived_update",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")


def _create_postgresql_archive_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION newsradar_guard_archived_daily_report()
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
    op.execute(
        """
        CREATE TRIGGER trg_daily_report_archived_mutation
        BEFORE UPDATE OR DELETE ON daily_reports
        FOR EACH ROW EXECUTE FUNCTION newsradar_guard_archived_daily_report()
        """
    )
    op.execute(
        """
        CREATE FUNCTION newsradar_guard_archived_daily_report_item()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            report_ids integer[];
        BEGIN
            IF TG_OP = 'INSERT' THEN
                report_ids := ARRAY[NEW.daily_report_id];
            ELSIF TG_OP = 'DELETE' THEN
                report_ids := ARRAY[OLD.daily_report_id];
            ELSE
                report_ids := ARRAY[OLD.daily_report_id, NEW.daily_report_id];
            END IF;

            PERFORM id
            FROM daily_reports
            WHERE id = ANY(report_ids)
            ORDER BY id
            FOR UPDATE;

            IF EXISTS (
                SELECT 1 FROM daily_reports
                WHERE id = ANY(report_ids) AND status = 'archived'
            ) THEN
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
    op.execute(
        """
        CREATE TRIGGER trg_daily_report_item_archived_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON daily_report_items
        FOR EACH ROW EXECUTE FUNCTION newsradar_guard_archived_daily_report_item()
        """
    )


def _drop_postgresql_archive_guards() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_daily_report_item_archived_mutation "
        "ON daily_report_items"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_daily_report_archived_mutation ON daily_reports"
    )
    op.execute("DROP FUNCTION IF EXISTS newsradar_guard_archived_daily_report_item()")
    op.execute("DROP FUNCTION IF EXISTS newsradar_guard_archived_daily_report()")
