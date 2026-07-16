from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from newsradar.settings import Settings


def test_runtime_closure_v1_2_real_postgresql_state() -> None:
    if os.getenv("NEWSRADAR_RUN_POSTGRES_ACCEPTANCE") != "1":
        pytest.skip("set NEWSRADAR_RUN_POSTGRES_ACCEPTANCE=1 to run real PostgreSQL acceptance")
    settings = Settings()
    if not settings.database_url or not settings.database_url.startswith("postgresql"):
        pytest.skip("real PostgreSQL is not configured")
    engine = create_engine(settings.database_url, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            columns = {
                column["name"]
                for column in inspect(connection).get_columns("source_definitions")
            }
            assert {
                "catalog_state",
                "catalog_archived_at",
                "catalog_archive_reason",
            } <= columns
            assert connection.execute(
                text("select count(*) from source_definitions where catalog_state='current'")
            ).scalar_one() == 187
            assert connection.execute(
                text("select count(*) from source_definitions where catalog_state='archived'")
            ).scalar_one() == 2
            assert connection.execute(
                text(
                    "select count(*) from workers where status='idle' "
                    "and last_heartbeat_at > now() - interval '5 minutes'"
                )
            ).scalar_one() >= 1
    except SQLAlchemyError as error:
        pytest.skip(f"real PostgreSQL is unavailable: {error.__class__.__name__}")
    finally:
        engine.dispose()

