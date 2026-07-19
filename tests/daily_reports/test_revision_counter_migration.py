from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    text,
)

from newsradar.db.models import Base

MIGRATION_ERROR = "cannot drop daily-report revision counters with retained high-water marks"


def _migration() -> ModuleType:
    migration_path = (
        Path(__file__).parents[2]
        / "migrations"
        / "versions"
        / "20260719_0032_daily_report_revision_counters.py"
    )
    assert migration_path.is_file()
    spec = spec_from_file_location("daily_report_revision_counters", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _daily_reports_table(engine) -> None:
    metadata = MetaData()
    Table(
        "daily_reports",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("report_date", Date, nullable=False),
        Column("window_hours", Integer, nullable=False),
        Column("revision", Integer, nullable=False),
        Column("status", String(16), nullable=False, server_default="draft"),
        Column("deleted_at", DateTime),
    )
    metadata.create_all(engine)


def test_model_declares_daily_report_revision_counter_table() -> None:
    table = Base.metadata.tables.get("daily_report_revision_counters")

    assert table is not None
    assert tuple(column.name for column in table.primary_key.columns) == (
        "report_date",
        "window_hours",
    )
    assert table.c.highest_revision.nullable is False


def test_migration_backfills_existing_revision_high_water_marks() -> None:
    migration = _migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _daily_reports_table(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO daily_reports "
                "(id, report_date, window_hours, revision) VALUES "
                "(1, '2026-07-19', 24, 1), "
                "(2, '2026-07-19', 24, 3), "
                "(3, '2026-07-19', 48, 2), "
                "(4, '2026-07-20', 24, 7)"
            )
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        assert connection.execute(
            text(
                "SELECT report_date, window_hours, highest_revision "
                "FROM daily_report_revision_counters "
                "ORDER BY report_date, window_hours"
            )
        ).all() == [
            ("2026-07-19", 24, 3),
            ("2026-07-19", 48, 2),
            ("2026-07-20", 24, 7),
        ]


def test_postgresql_upgrade_locks_reports_before_counter_backfill() -> None:
    migration = _migration()
    statements: list[str] = []

    class Bind:
        dialect = SimpleNamespace(name="postgresql")

        @staticmethod
        def execute(statement) -> None:
            statements.append(str(statement))

    migration.op = SimpleNamespace(
        get_bind=lambda: Bind(),
        create_table=lambda *_args, **_kwargs: None,
        execute=lambda statement: statements.append(str(statement)),
    )

    migration.upgrade()

    assert statements[0] == "LOCK TABLE daily_reports IN SHARE MODE"
    assert statements[1].startswith("INSERT INTO daily_report_revision_counters")


def test_migration_downgrade_refuses_to_discard_retained_high_water_mark() -> None:
    migration = _migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _daily_reports_table(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO daily_reports "
                "(id, report_date, window_hours, revision) VALUES "
                "(1, '2026-07-19', 24, 1), "
                "(2, '2026-07-19', 24, 2)"
            )
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        connection.execute(
            text(
                "UPDATE daily_reports SET deleted_at = '2026-07-20 00:00:00' "
                "WHERE revision = 2"
            )
        )
        connection.execute(text("DELETE FROM daily_reports WHERE revision = 2"))

        with pytest.raises(RuntimeError, match=f"^{MIGRATION_ERROR}$"):
            migration.downgrade()


def test_postgresql_downgrade_locks_reports_before_checking_high_water() -> None:
    migration = _migration()
    statements: list[str] = []

    class Result:
        @staticmethod
        def first() -> None:
            return None

    class Bind:
        dialect = SimpleNamespace(name="postgresql")

        @staticmethod
        def execute(statement) -> Result:
            statements.append(str(statement))
            return Result()

    class MigrationOperations:
        @staticmethod
        def get_bind() -> Bind:
            return Bind()

        @staticmethod
        def drop_table(_table_name: str) -> None:
            return None

        @staticmethod
        def execute(statement) -> None:
            statements.append(str(statement))

    migration.op = MigrationOperations()

    migration.downgrade()

    assert statements[0] == "LOCK TABLE daily_reports IN SHARE MODE"
    assert "OLD.status <> 'archived' OR OLD.deleted_at IS NULL" in statements[-1]


def test_postgresql_guard_allows_only_trashed_archived_or_draft_delete() -> None:
    migration = _migration()
    statements: list[str] = []
    migration.op = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        execute=lambda statement: statements.append(str(statement)),
    )

    migration._replace_archived_report_guard(allow_trashed_draft_delete=True)

    normalized = " ".join(statements[-1].split())
    assert (
        "OLD.status NOT IN ('archived', 'draft') OR OLD.deleted_at IS NULL"
        in normalized
    )
    assert "OLD.status <> 'archived' OR OLD.deleted_at IS NULL" not in normalized
    assert "NEW.generation_summary::text IS DISTINCT FROM" in normalized
    assert "daily_report_purge_transitions" in normalized
