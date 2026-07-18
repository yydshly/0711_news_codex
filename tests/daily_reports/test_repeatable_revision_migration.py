from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Column, Date, DateTime, Integer, MetaData, Table, create_engine, text
from sqlalchemy.exc import IntegrityError

from newsradar.db.models import DailyReportRecord

IDENTITY_ACTIVE = "supersedes_report_id IS NULL AND deleted_at IS NULL"
SUCCESSOR_ACTIVE = "supersedes_report_id IS NOT NULL AND deleted_at IS NULL"
DOWNGRADE_ERROR = "cannot restore unconditional daily-report identity uniqueness"


def _migration() -> ModuleType:
    migration_path = (
        Path(__file__).parents[2]
        / "migrations"
        / "versions"
        / "20260719_0031_active_daily_report_revision_indexes.py"
    )
    assert migration_path.is_file()
    spec = spec_from_file_location("active_daily_report_indexes", migration_path)
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
        Column("source_operation_id", Integer, nullable=False),
        Column("supersedes_report_id", Integer),
        Column("deleted_at", DateTime),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX uq_daily_report_identity ON daily_reports "
                "(report_date, window_hours, source_operation_id) "
                "WHERE supersedes_report_id IS NULL"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX uq_daily_report_supersedes ON daily_reports "
                "(supersedes_report_id)"
            )
        )


def test_model_declares_active_daily_report_identity_indexes() -> None:
    indexes = {index.name: index for index in DailyReportRecord.__table__.indexes}

    identity = indexes["uq_daily_report_identity"]
    successor = indexes["uq_daily_report_supersedes"]

    assert identity.unique is True
    assert successor.unique is True
    assert str(identity.dialect_options["postgresql"]["where"]) == IDENTITY_ACTIVE
    assert str(identity.dialect_options["sqlite"]["where"]) == IDENTITY_ACTIVE
    assert str(successor.dialect_options["postgresql"]["where"]) == SUCCESSOR_ACTIVE
    assert str(successor.dialect_options["sqlite"]["where"]) == SUCCESSOR_ACTIVE


def test_migration_creates_active_partial_indexes() -> None:
    migration = _migration()
    created: dict[str, dict[str, object]] = {}
    migration.op = SimpleNamespace(
        drop_index=lambda *args, **kwargs: None,
        create_index=lambda name, table, columns, **kwargs: created.__setitem__(
            name, {"table": table, "columns": columns, **kwargs}
        ),
    )

    migration.upgrade()

    assert migration.revision == "20260719_0031"
    assert migration.down_revision == "20260718_0030"
    assert created["uq_daily_report_identity"]["columns"] == [
        "report_date",
        "window_hours",
        "source_operation_id",
    ]
    assert str(created["uq_daily_report_identity"]["postgresql_where"]) == IDENTITY_ACTIVE
    assert str(created["uq_daily_report_identity"]["sqlite_where"]) == IDENTITY_ACTIVE
    assert created["uq_daily_report_supersedes"]["columns"] == ["supersedes_report_id"]
    assert str(created["uq_daily_report_supersedes"]["postgresql_where"]) == SUCCESSOR_ACTIVE
    assert str(created["uq_daily_report_supersedes"]["sqlite_where"]) == SUCCESSOR_ACTIVE


def test_migration_enforces_active_row_uniqueness() -> None:
    migration = _migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _daily_reports_table(engine)

    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        indexes = dict(
            connection.execute(
                text(
                    "SELECT name, sql FROM sqlite_master WHERE type = 'index' "
                    "AND name IN ('uq_daily_report_identity', 'uq_daily_report_supersedes')"
                )
            ).all()
        )
        assert IDENTITY_ACTIVE in indexes["uq_daily_report_identity"]
        assert SUCCESSOR_ACTIVE in indexes["uq_daily_report_supersedes"]

        connection.execute(
            text(
                "INSERT INTO daily_reports "
                "(id, report_date, window_hours, source_operation_id, deleted_at) VALUES "
                "(1, '2026-07-19', 24, 7, NULL), "
                "(2, '2026-07-19', 24, 7, '2026-07-19T00:00:00')"
            )
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO daily_reports "
                    "(id, report_date, window_hours, source_operation_id, deleted_at) "
                    "VALUES (3, '2026-07-19', 24, 7, NULL)"
                )
            )

        connection.execute(
            text(
                "INSERT INTO daily_reports "
                "(id, report_date, window_hours, source_operation_id, supersedes_report_id, "
                "deleted_at) VALUES "
                "(4, '2026-07-20', 24, 8, 1, NULL), "
                "(5, '2026-07-20', 24, 9, 1, '2026-07-19T00:00:00')"
            )
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO daily_reports "
                    "(id, report_date, window_hours, source_operation_id, supersedes_report_id, "
                    "deleted_at) VALUES (6, '2026-07-20', 24, 10, 1, NULL)"
                )
            )


@pytest.mark.parametrize(
    "rows",
    (
        "(1, '2026-07-19', 24, 7, NULL, NULL), "
        "(2, '2026-07-19', 24, 7, NULL, '2026-07-19T00:00:00')",
        "(1, '2026-07-19', 24, 7, 9, NULL), "
        "(2, '2026-07-20', 24, 8, 9, '2026-07-19T00:00:00')",
    ),
)
def test_migration_downgrade_refuses_conflicting_historical_rows(rows: str) -> None:
    migration = _migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _daily_reports_table(engine)

    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        connection.execute(
            text(
                "INSERT INTO daily_reports "
                "(id, report_date, window_hours, source_operation_id, supersedes_report_id, "
                f"deleted_at) VALUES {rows}"
            )
        )

        with pytest.raises(RuntimeError, match=f"^{DOWNGRADE_ERROR}$"):
            migration.downgrade()
