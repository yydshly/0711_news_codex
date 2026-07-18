from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from newsradar.db import session as session_module
from newsradar.settings import Settings


def test_postgres_engine_sets_bounded_lock_timeout(monkeypatch) -> None:
    listeners: list[object] = []

    class Engine:
        class dialect:
            name = "postgresql"

    engine = Engine()

    def listen(engine, event_name, callback):
        assert event_name == "connect"
        listeners.append(callback)

    monkeypatch.setattr(session_module, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(session_module.event, "listen", listen)
    session_module.create_database_engine(
        Settings(
            database_url="postgresql+psycopg://user:password@127.0.0.1:5432/news",
            db_lock_timeout_seconds=5,
        )
    )

    commands: list[str] = []

    class Cursor:
        def execute(self, command: str) -> None:
            commands.append(command)

        def close(self) -> None:
            pass

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

    assert len(listeners) == 1
    listeners[0](Connection(), None)  # type: ignore[operator]
    assert commands == ["SET lock_timeout = '5s'"]


def test_sqlite_engine_enables_foreign_key_enforcement(tmp_path: Path) -> None:
    engine = session_module.create_database_engine(
        Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'session.sqlite3'}")
    )

    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1


def test_create_session_reuses_one_engine_for_the_same_database(monkeypatch) -> None:
    engines: list[object] = []

    def create_engine(settings):
        engine = object()
        engines.append(engine)
        return engine

    monkeypatch.setattr(session_module, "create_database_engine", create_engine)
    monkeypatch.setattr(session_module, "Session", lambda engine: engine)
    session_module._cached_database_engine.cache_clear()
    settings = Settings(database_url="sqlite+pysqlite:///newsradar.db")

    first = session_module.create_session(settings)
    second = session_module.create_session(settings)

    assert first is second
    assert len(engines) == 1
    session_module._cached_database_engine.cache_clear()
