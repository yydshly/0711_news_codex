from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Column, Date, Integer, MetaData, Table, create_engine, inspect

from newsradar.db.models import DailyAutomationConfigRecord, DailyReportRecord


def test_automation_config_model_defines_singleton_scheduler_contract() -> None:
    table = DailyAutomationConfigRecord.__table__

    assert set(table.columns.keys()) == {
        "id",
        "enabled",
        "timezone",
        "daily_time",
        "window_hours",
        "resource_profile",
        "last_scheduled_date",
        "last_retention_date",
        "last_run_id",
        "next_run_at",
        "created_at",
        "updated_at",
    }
    assert {
        constraint.name
        for constraint in table.constraints
        if constraint.name is not None
    } >= {
        "ck_daily_automation_singleton",
        "ck_daily_automation_window",
        "ck_daily_automation_resource_profile",
    }
    assert {
        index.name: tuple(column.name for column in index.columns)
        for index in table.indexes
    } == {"ix_daily_automation_next_run": ("enabled", "next_run_at")}
    assert DailyAutomationConfigRecord.enabled.default.arg is False
    assert DailyAutomationConfigRecord.window_hours.default.arg == 24
    assert DailyAutomationConfigRecord.last_retention_date.nullable
    assert next(iter(DailyAutomationConfigRecord.last_run_id.foreign_keys)).ondelete == "SET NULL"


def test_daily_report_model_includes_retention_timestamps_and_indexes() -> None:
    table = DailyReportRecord.__table__

    assert {"pinned_at", "deleted_at", "purge_after"} <= set(table.columns.keys())
    assert all(table.columns[name].nullable for name in ("pinned_at", "deleted_at", "purge_after"))
    assert {
        index.name: tuple(column.name for column in index.columns)
        for index in table.indexes
    }.items() >= {
        "ix_daily_reports_deleted_purge": ("deleted_at", "purge_after"),
        "ix_daily_reports_pinned_date": ("pinned_at", "report_date"),
    }.items()


def test_automation_migration_round_trip_adds_then_removes_last_retention_date() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    Table("daily_autopilot_runs", metadata, Column("id", Integer, primary_key=True))
    Table(
        "daily_reports",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("report_date", Date, nullable=False),
    )
    metadata.create_all(engine)
    migration_path = (
        Path(__file__).parents[2]
        / "migrations"
        / "versions"
        / "20260718_0029_daily_automation_retention.py"
    )
    spec = spec_from_file_location("daily_automation_retention_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert "last_retention_date" in {
            column["name"]
            for column in inspect(connection).get_columns("daily_automation_config")
        }
        assert "daily_report_purge_transitions" in inspect(connection).get_table_names()
        assert "daily_report_purge_transition_barrier" in inspect(connection).get_table_names()
        assert "daily_report_audio_purge_queue" in inspect(connection).get_table_names()

        migration.downgrade()
        assert "daily_automation_config" not in inspect(connection).get_table_names()
        assert "daily_report_purge_transitions" not in inspect(connection).get_table_names()
        assert "daily_report_purge_transition_barrier" not in inspect(connection).get_table_names()
        assert "daily_report_audio_purge_queue" not in inspect(connection).get_table_names()


def test_postgresql_guard_sql_rejects_draft_delete_and_allows_only_purge_reparent() -> None:
    migration_path = (
        Path(__file__).parents[2]
        / "migrations"
        / "versions"
        / "20260718_0029_daily_automation_retention.py"
    )
    spec = spec_from_file_location("daily_automation_retention_postgresql", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements: list[str] = []
    migration.op = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        execute=lambda statement: statements.append(str(statement)),
    )

    migration._allow_archived_report_retention_mutations()

    function_sql = "\n".join(statements)
    normalized_sql = " ".join(function_sql.split())
    assert "IF TG_OP = 'DELETE' THEN" in function_sql
    assert "OLD.status <> 'archived'" in function_sql
    assert "OLD.deleted_at IS NULL" in function_sql
    assert "RETURN OLD" in function_sql
    assert "parent.deleted_at IS NOT NULL" in function_sql
    assert "daily_report_purge_transitions" in function_sql
    assert (
        "transition.predecessor_report_id IS NOT DISTINCT FROM parent.supersedes_report_id"
        in normalized_sql
    )
    assert (
        "NEW.supersedes_report_id IS NOT DISTINCT FROM transition.temporary_parent_id"
        in normalized_sql
    )
    assert (
        "NEW.supersedes_report_id IS NOT DISTINCT FROM transition.predecessor_report_id"
        in normalized_sql
    )
    assert "NOT EXISTS (" in function_sql
    assert "newsradar_guard_daily_report_purge_transition" in function_sql
    assert "WITH RECURSIVE descendants" in function_sql
    assert "TG_OP = 'UPDATE'" in function_sql
    assert "newsradar_guard_archived_daily_report_item" in function_sql
    assert "pg_trigger_depth" not in function_sql
    # Custom GUCs are application-settable session state, never authorization facts.
    assert "set_config" not in function_sql
    assert "current_setting" not in function_sql
    assert (
        "IF TG_OP = 'DELETE' AND NOT EXISTS ( SELECT 1 FROM daily_reports "
        "WHERE id = OLD.daily_report_id ) THEN RETURN OLD; END IF;"
        in normalized_sql
    )
