"""PostgreSQL-only regression coverage for archived report retention guards."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newsradar.db.models import DailyReportRecord, OperationRunRecord
from newsradar.db.session import create_database_engine
from newsradar.settings import get_settings


def test_postgresql_retention_update_preserves_exact_archived_json_immutability() -> None:
    if os.getenv("NEWSRADAR_RUN_POSTGRES_ACCEPTANCE") != "1":
        pytest.skip("set NEWSRADAR_RUN_POSTGRES_ACCEPTANCE=1 to run real PostgreSQL acceptance")
    if not (get_settings().database_url or "").startswith("postgresql"):
        pytest.skip("project-local PostgreSQL is not configured")

    migration_path = (
        Path(__file__).parents[2]
        / "migrations"
        / "versions"
        / "20260718_0030_fix_daily_report_retention_json_guard.py"
    )
    spec = spec_from_file_location("retention_json_guard_postgresql", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_database_engine()
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(connection)
        try:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            operation = OperationRunRecord(
                operation_type="event_pipeline",
                trigger="test",
                status="succeeded",
                requested_scope={},
                result_summary={},
                created_at=datetime(2099, 1, 1, tzinfo=UTC),
                updated_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
            session.add(operation)
            session.flush()
            report = DailyReportRecord(
                report_date=date(2099, 1, 1),
                timezone="UTC",
                window_hours=24,
                window_start=datetime(2098, 12, 31, tzinfo=UTC),
                window_end=datetime(2099, 1, 1, tzinfo=UTC),
                source_operation_id=operation.id,
                status="archived",
                revision=1,
                generation_summary={"a": 1, "b": 2},
                generated_at=datetime(2099, 1, 1, tzinfo=UTC),
                archived_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
            session.add(report)
            session.flush()

            session.execute(
                text(
                    "UPDATE daily_reports SET deleted_at = :deleted_at, "
                    "purge_after = :purge_after WHERE id = :id"
                ),
                {
                    "id": report.id,
                    "deleted_at": datetime(2099, 1, 2, tzinfo=UTC),
                    "purge_after": datetime(2099, 2, 1, tzinfo=UTC),
                },
            )
            with pytest.raises(IntegrityError, match="daily_report_archived_immutable"):
                with session.begin_nested():
                    session.execute(
                        text(
                            "UPDATE daily_reports SET generation_summary = "
                            "CAST(:summary AS json) WHERE id = :id"
                        ),
                        {"id": report.id, "summary": '{\"b\":2,\"a\":1}'},
                    )
        finally:
            session.close()
            transaction.rollback()
            engine.dispose()
