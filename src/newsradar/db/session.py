from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from newsradar.settings import Settings, get_settings


def create_database_engine(settings: Settings | None = None) -> Engine:
    resolved = settings or get_settings()
    if not resolved.database_url:
        raise RuntimeError("DATABASE_URL is required for database operations")
    return create_engine(resolved.database_url, pool_pre_ping=True)


def create_session(settings: Settings | None = None) -> Session:
    return Session(create_database_engine(settings))
