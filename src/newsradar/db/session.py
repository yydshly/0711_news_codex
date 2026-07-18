from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from newsradar.settings import Settings, get_settings


def create_database_engine(settings: Settings | None = None) -> Engine:
    resolved = settings or get_settings()
    if not resolved.database_url:
        raise RuntimeError("DATABASE_URL is required for database operations")
    engine = create_engine(resolved.database_url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":

        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

        event.listen(engine, "connect", enable_sqlite_foreign_keys)
    elif engine.dialect.name == "postgresql":

        def set_lock_timeout(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            try:
                seconds = resolved.db_lock_timeout_seconds
                cursor.execute(f"SET lock_timeout = '{seconds:g}s'")
            finally:
                cursor.close()

        event.listen(engine, "connect", set_lock_timeout)
    return engine


@lru_cache(maxsize=8)
def _cached_database_engine(
    database_url: str | None, db_lock_timeout_seconds: float
) -> Engine:
    """Keep one bounded connection pool per database configuration and process."""
    return create_database_engine(
        Settings(
            database_url=database_url,
            db_lock_timeout_seconds=db_lock_timeout_seconds,
        )
    )


def create_session(settings: Settings | None = None) -> Session:
    resolved = settings or get_settings()
    engine = _cached_database_engine(
        resolved.database_url,
        resolved.db_lock_timeout_seconds,
    )
    return Session(engine)
