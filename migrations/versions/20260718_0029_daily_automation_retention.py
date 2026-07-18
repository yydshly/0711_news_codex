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
    op.create_table(
        "daily_report_purge_transitions",
        sa.Column(
            "child_report_id",
            sa.Integer(),
            sa.ForeignKey("daily_reports.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("deleted_parent_id", sa.Integer(), nullable=False),
        sa.Column("predecessor_report_id", sa.Integer()),
        sa.Column("temporary_parent_id", sa.Integer(), nullable=False),
    )
    _allow_archived_report_retention_mutations()


def downgrade() -> None:
    _restore_strict_archived_report_guards()
    op.drop_table("daily_report_purge_transitions")
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
                (
                    NEW.supersedes_report_id IS NOT OLD.supersedes_report_id AND
                    NOT (
                        (
                            EXISTS (
                                SELECT 1
                                FROM daily_report_purge_transitions AS transition
                                JOIN daily_reports AS parent
                                  ON parent.id = transition.deleted_parent_id
                                WHERE transition.child_report_id = OLD.id
                                  AND transition.deleted_parent_id = OLD.supersedes_report_id
                                  AND transition.predecessor_report_id
                                      IS parent.supersedes_report_id
                                  AND NEW.supersedes_report_id IS transition.temporary_parent_id
                                  AND parent.status = 'archived'
                                  AND parent.deleted_at IS NOT NULL
                            )
                        ) OR (
                            EXISTS (
                                SELECT 1
                                FROM daily_report_purge_transitions AS transition
                                WHERE transition.child_report_id = OLD.id
                                  AND NOT EXISTS (
                                      SELECT 1 FROM daily_reports AS deleted_parent
                                      WHERE deleted_parent.id = transition.deleted_parent_id
                                  )
                                  AND OLD.supersedes_report_id IS transition.temporary_parent_id
                                  AND NEW.supersedes_report_id IS transition.predecessor_report_id
                            )
                        )
                    )
                ) OR
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
        _create_sqlite_purge_transition_guards()
        return

    op.execute(
        """
        CREATE OR REPLACE FUNCTION newsradar_guard_archived_daily_report()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status <> 'archived' OR OLD.deleted_at IS NULL THEN
                    RAISE EXCEPTION 'daily_report_archived_immutable'
                        USING ERRCODE = '23514';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.status = 'archived' THEN
                IF ROW(
                    NEW.id, NEW.report_date, NEW.timezone, NEW.window_hours,
                    NEW.window_start, NEW.window_end, NEW.source_operation_id,
                    NEW.status, NEW.revision,
                    NEW.generation_summary, NEW.generated_at, NEW.archived_at
                ) IS DISTINCT FROM ROW(
                    OLD.id, OLD.report_date, OLD.timezone, OLD.window_hours,
                    OLD.window_start, OLD.window_end, OLD.source_operation_id,
                    OLD.status, OLD.revision,
                    OLD.generation_summary, OLD.generated_at, OLD.archived_at
                ) THEN
                    RAISE EXCEPTION 'daily_report_archived_immutable'
                        USING ERRCODE = '23514';
                END IF;
                IF NEW.supersedes_report_id IS DISTINCT FROM OLD.supersedes_report_id
                   AND NOT (
                       (
                           EXISTS (
                               SELECT 1
                               FROM daily_report_purge_transitions AS transition
                               JOIN daily_reports AS parent
                                 ON parent.id = transition.deleted_parent_id
                               WHERE transition.child_report_id = OLD.id
                                 AND transition.deleted_parent_id = OLD.supersedes_report_id
                                 AND transition.predecessor_report_id
                                     IS NOT DISTINCT FROM parent.supersedes_report_id
                                 AND NEW.supersedes_report_id
                                     IS NOT DISTINCT FROM transition.temporary_parent_id
                                 AND parent.status = 'archived'
                                 AND parent.deleted_at IS NOT NULL
                           )
                       ) OR (
                           EXISTS (
                               SELECT 1
                               FROM daily_report_purge_transitions AS transition
                               WHERE transition.child_report_id = OLD.id
                                 AND NOT EXISTS (
                                     SELECT 1 FROM daily_reports AS deleted_parent
                                     WHERE deleted_parent.id = transition.deleted_parent_id
                                 )
                                 AND OLD.supersedes_report_id
                                     IS NOT DISTINCT FROM transition.temporary_parent_id
                                 AND NEW.supersedes_report_id
                                     IS NOT DISTINCT FROM transition.predecessor_report_id
                           )
                       )
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
    op.execute(
        """
        CREATE OR REPLACE FUNCTION newsradar_guard_archived_daily_report_item()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            report_ids integer[];
        BEGIN
            IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
                RETURN OLD;
            END IF;
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
    _create_postgresql_purge_transition_guards()


def _create_sqlite_purge_transition_guards() -> None:
    op.execute(
        """
        CREATE TRIGGER trg_daily_report_purge_transition_insert
        BEFORE INSERT ON daily_report_purge_transitions
        FOR EACH ROW WHEN NOT (
            EXISTS (
                SELECT 1
                FROM daily_reports AS child
                JOIN daily_reports AS parent ON parent.id = NEW.deleted_parent_id
                WHERE child.id = NEW.child_report_id
                  AND child.status = 'archived'
                  AND child.supersedes_report_id IS NEW.deleted_parent_id
                  AND parent.status = 'archived'
                  AND parent.deleted_at IS NOT NULL
                  AND NEW.predecessor_report_id IS parent.supersedes_report_id
            ) AND NEW.temporary_parent_id IN (
                WITH RECURSIVE descendants(id) AS (
                    SELECT NEW.child_report_id
                    UNION ALL
                    SELECT report.id
                    FROM daily_reports AS report
                    JOIN descendants ON report.supersedes_report_id = descendants.id
                )
                SELECT descendants.id
                FROM descendants
                WHERE NOT EXISTS (
                    SELECT 1 FROM daily_reports AS child
                    WHERE child.supersedes_report_id = descendants.id
                )
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'daily_report_archived_immutable');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_daily_report_purge_transition_update
        BEFORE UPDATE ON daily_report_purge_transitions
        BEGIN
            SELECT RAISE(ABORT, 'daily_report_archived_immutable');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_daily_report_purge_transition_delete
        BEFORE DELETE ON daily_report_purge_transitions
        FOR EACH ROW WHEN NOT EXISTS (
            SELECT 1
            FROM daily_reports AS child
            WHERE child.id = OLD.child_report_id
              AND child.supersedes_report_id IS OLD.predecessor_report_id
              AND NOT EXISTS (
                  SELECT 1 FROM daily_reports AS deleted_parent
                  WHERE deleted_parent.id = OLD.deleted_parent_id
              )
        )
        BEGIN
            SELECT RAISE(ABORT, 'daily_report_archived_immutable');
        END
        """
    )


def _create_postgresql_purge_transition_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION newsradar_guard_daily_report_purge_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NOT EXISTS (
                    WITH RECURSIVE descendants(id) AS (
                        SELECT NEW.child_report_id
                        UNION ALL
                        SELECT report.id
                        FROM daily_reports AS report
                        JOIN descendants
                          ON report.supersedes_report_id = descendants.id
                    )
                    SELECT 1
                    FROM daily_reports AS child
                    JOIN daily_reports AS parent
                      ON parent.id = NEW.deleted_parent_id
                    WHERE child.id = NEW.child_report_id
                      AND child.status = 'archived'
                      AND child.supersedes_report_id = NEW.deleted_parent_id
                      AND parent.status = 'archived'
                      AND parent.deleted_at IS NOT NULL
                      AND NEW.predecessor_report_id
                          IS NOT DISTINCT FROM parent.supersedes_report_id
                      AND EXISTS (
                          SELECT 1
                          FROM descendants
                          WHERE descendants.id = NEW.temporary_parent_id
                            AND NOT EXISTS (
                                SELECT 1 FROM daily_reports AS next_report
                                WHERE next_report.supersedes_report_id = descendants.id
                            )
                      )
                ) THEN
                    RAISE EXCEPTION 'daily_report_archived_immutable'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'daily_report_archived_immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM daily_reports AS child
                WHERE child.id = OLD.child_report_id
                  AND child.supersedes_report_id
                      IS NOT DISTINCT FROM OLD.predecessor_report_id
                  AND NOT EXISTS (
                      SELECT 1 FROM daily_reports AS deleted_parent
                      WHERE deleted_parent.id = OLD.deleted_parent_id
                  )
            ) THEN
                RAISE EXCEPTION 'daily_report_archived_immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN OLD;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_daily_report_purge_transition_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON daily_report_purge_transitions
        FOR EACH ROW EXECUTE FUNCTION newsradar_guard_daily_report_purge_transition()
        """
    )


def _restore_strict_archived_report_guards() -> None:
    if op.get_bind().dialect.name == "sqlite":
        if not _sqlite_archived_report_guards_exist():
            return
        op.execute("DROP TRIGGER IF EXISTS trg_daily_report_archived_update")
        op.execute("DROP TRIGGER IF EXISTS trg_daily_report_archived_delete")
        op.execute("DROP TRIGGER IF EXISTS trg_daily_report_purge_transition_insert")
        op.execute("DROP TRIGGER IF EXISTS trg_daily_report_purge_transition_update")
        op.execute("DROP TRIGGER IF EXISTS trg_daily_report_purge_transition_delete")
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
        "DROP TRIGGER IF EXISTS trg_daily_report_purge_transition_mutation "
        "ON daily_report_purge_transitions"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS newsradar_guard_daily_report_purge_transition()"
    )
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
    op.execute(
        """
        CREATE OR REPLACE FUNCTION newsradar_guard_archived_daily_report_item()
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


def _sqlite_archived_report_guards_exist() -> bool:
    return bool(
        op.get_bind().scalar(
            sa.text(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'trigger' AND name = 'trg_daily_report_archived_update'"
            )
        )
    )
