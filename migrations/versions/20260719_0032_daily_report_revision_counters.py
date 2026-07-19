"""Persist revision high-water marks and permit guarded trashed-draft purge."""

import sqlalchemy as sa
from alembic import op

revision = "20260719_0032"
down_revision = "20260719_0031"
branch_labels = None
depends_on = None

DOWNGRADE_ERROR = (
    "cannot drop daily-report revision counters with retained high-water marks"
)


def upgrade() -> None:
    op.create_table(
        "daily_report_revision_counters",
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False),
        sa.Column("highest_revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "window_hours IN (24, 48, 72)",
            name="ck_daily_report_revision_counter_window",
        ),
        sa.CheckConstraint(
            "highest_revision > 0",
            name="ck_daily_report_revision_counter_positive",
        ),
        sa.PrimaryKeyConstraint(
            "report_date",
            "window_hours",
            name="pk_daily_report_revision_counters",
        ),
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("LOCK TABLE daily_reports IN SHARE MODE"))
    op.execute(
        sa.text(
            "INSERT INTO daily_report_revision_counters "
            "(report_date, window_hours, highest_revision) "
            "SELECT report_date, window_hours, MAX(revision) "
            "FROM daily_reports GROUP BY report_date, window_hours"
        )
    )
    _replace_archived_report_guard(allow_trashed_draft_delete=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("LOCK TABLE daily_reports IN SHARE MODE"))
    retained_high_water = bind.execute(
        sa.text(
            "SELECT counter.report_date "
            "FROM daily_report_revision_counters AS counter "
            "LEFT JOIN ("
            "SELECT report_date, window_hours, MAX(revision) AS highest_revision "
            "FROM daily_reports GROUP BY report_date, window_hours"
            ") AS report ON report.report_date = counter.report_date "
            "AND report.window_hours = counter.window_hours "
            "WHERE counter.highest_revision > COALESCE(report.highest_revision, 0) "
            "LIMIT 1"
        )
    ).first()
    if retained_high_water is not None:
        raise RuntimeError(DOWNGRADE_ERROR)
    op.drop_table("daily_report_revision_counters")
    _replace_archived_report_guard(allow_trashed_draft_delete=False)


def _replace_archived_report_guard(*, allow_trashed_draft_delete: bool) -> None:
    dialect_name = op.get_bind().dialect.name
    if dialect_name == "sqlite":
        delete_condition = (
            "OLD.deleted_at IS NULL "
            "OR OLD.status NOT IN ('archived', 'draft')"
            if allow_trashed_draft_delete
            else "OLD.status = 'archived' AND OLD.deleted_at IS NULL"
        )
        op.execute("DROP TRIGGER IF EXISTS trg_daily_report_archived_delete")
        op.execute(
            f"""
            CREATE TRIGGER trg_daily_report_archived_delete
            BEFORE DELETE ON daily_reports
            FOR EACH ROW WHEN {delete_condition}
            BEGIN
                SELECT RAISE(ABORT, 'daily_report_archived_immutable');
            END
            """
        )
        return
    if dialect_name != "postgresql":
        return

    delete_condition = (
        "OLD.status NOT IN ('archived', 'draft') OR OLD.deleted_at IS NULL"
        if allow_trashed_draft_delete
        else "OLD.status <> 'archived' OR OLD.deleted_at IS NULL"
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION newsradar_guard_archived_daily_report()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF {delete_condition} THEN
                    RAISE EXCEPTION 'daily_report_archived_immutable'
                        USING ERRCODE = '23514';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.status = 'archived' THEN
                IF ROW(
                    NEW.id, NEW.report_date, NEW.timezone, NEW.window_hours,
                    NEW.window_start, NEW.window_end, NEW.source_operation_id,
                    NEW.status, NEW.revision, NEW.generated_at, NEW.archived_at
                ) IS DISTINCT FROM ROW(
                    OLD.id, OLD.report_date, OLD.timezone, OLD.window_hours,
                    OLD.window_start, OLD.window_end, OLD.source_operation_id,
                    OLD.status, OLD.revision, OLD.generated_at, OLD.archived_at
                ) OR NEW.generation_summary::text IS DISTINCT FROM
                    OLD.generation_summary::text THEN
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
