from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError
from typer.testing import CliRunner

from newsradar import cli
from newsradar.cli import app


def test_web_command_uses_local_only_defaults(monkeypatch):
    called = {}

    def fake_run(application, *, host, port, log_level):
        called.update(host=host, port=port, log_level=log_level)

    monkeypatch.setattr("uvicorn.run", fake_run)

    result = CliRunner().invoke(app, ["web"])

    assert result.exit_code == 0
    assert called == {"host": "127.0.0.1", "port": 8765, "log_level": "info"}


class _StopWorkerLoop(Exception):
    pass


def _stub_worker_dependencies(monkeypatch, *, processed_results):
    class HandlerFactory:
        def __init__(self, *_args):
            pass

        @staticmethod
        def production(*_args):
            return object()

    class Router:
        def __init__(self, _handlers):
            pass

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeWorker:
        def __init__(self, *_args, **_kwargs):
            pass

        def run_once(self, _handler):
            return next(processed_results)

    monkeypatch.setattr(cli, "load_source_tree", lambda _root: [])
    monkeypatch.setattr(cli, "load_provider_tree", lambda _root: [])
    monkeypatch.setattr(cli, "OperationRouter", Router)
    monkeypatch.setattr(cli, "FetchOperationHandler", HandlerFactory)
    monkeypatch.setattr(cli, "SourceRemediationHandler", HandlerFactory)
    monkeypatch.setattr(cli, "CatalogRefreshHandler", HandlerFactory)
    monkeypatch.setattr(cli, "HighValueWaveHandler", HandlerFactory)
    monkeypatch.setattr(cli, "EventOperationHandler", HandlerFactory)
    monkeypatch.setattr(cli, "EventMergeOperationHandler", HandlerFactory)
    monkeypatch.setattr(cli, "Worker", FakeWorker)
    monkeypatch.setattr(cli, "create_session", Session)
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(worker_lease_seconds=30, worker_heartbeat_seconds=10),
    )

    from newsradar.daily_reports import audio_runtime, autopilot_runtime

    monkeypatch.setattr(audio_runtime, "DailyReportAudioHandler", HandlerFactory)
    monkeypatch.setattr(autopilot_runtime, "DailyAutopilotHandler", HandlerFactory)


def test_worker_checks_the_daily_schedule_at_most_once_per_minute(monkeypatch) -> None:
    _stub_worker_dependencies(monkeypatch, processed_results=iter([False] * 5))
    ticks = []
    monotonic_values = iter([0.0, 1.0, 59.9, 60.0, 60.1])
    sleeps = 0

    monkeypatch.setattr(cli, "_tick_daily_automation", lambda: ticks.append("tick"), raising=False)
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(monotonic_values))

    def fake_sleep(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 5:
            raise _StopWorkerLoop

    monkeypatch.setattr(cli.time, "sleep", fake_sleep)

    with pytest.raises(_StopWorkerLoop):
        cli.run_worker(once=False)

    assert ticks == ["tick", "tick"]


def test_worker_once_does_not_tick_or_wait(monkeypatch) -> None:
    _stub_worker_dependencies(monkeypatch, processed_results=iter([False]))
    ticks = []
    monkeypatch.setattr(cli, "_tick_daily_automation", lambda: ticks.append("tick"), raising=False)
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: pytest.fail("unexpected wait"))

    cli.run_worker(once=True)

    assert ticks == []


def test_daily_automation_tick_warns_once_when_database_access_fails(monkeypatch, capsys) -> None:
    class BrokenSession:
        def __enter__(self):
            raise SQLAlchemyError("database unavailable")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(cli, "create_session", BrokenSession)

    cli._tick_daily_automation()

    assert capsys.readouterr().err == "daily_automation_schedule_tick_failed\n"
