from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from newsradar.settings import Settings, get_settings


def create_database_engine(settings: Settings | None = None) -> Engine:
    resolved = settings or get_settings()
    if not resolved.database_url:
        raise RuntimeError("DATABASE_URL is required for database operations")
    engine = create_engine(resolved.database_url, pool_pre_ping=True)
    if engine.dialect.name == "postgresql":

        def set_lock_timeout(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            try:
                seconds = resolved.db_lock_timeout_seconds
                cursor.execute(f"SET lock_timeout = '{seconds:g}s'")
            finally:
                cursor.close()

        event.listen(engine, "connect", set_lock_timeout)
    return engine


def create_session(settings: Settings | None = None) -> Session:
    return Session(create_database_engine(settings))
