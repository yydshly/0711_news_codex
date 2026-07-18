"""Fix JSON comparisons in the archived daily-report retention guard."""

from alembic import op

revision = "20260718_0030"
down_revision = "20260718_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _replace_archived_report_guard()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    raise RuntimeError(
        "cannot safely downgrade daily-report retention guard: "
        "revision 20260718_0029 has an unsupported json comparison"
    )


def _replace_archived_report_guard() -> None:
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
