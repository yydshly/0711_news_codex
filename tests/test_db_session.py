from __future__ import annotations

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
