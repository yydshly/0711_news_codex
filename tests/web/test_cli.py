from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from newsradar import cli
from newsradar.cli import app
from newsradar.daily_reports.automation_repository import DailyAutomationRepository
from newsradar.daily_reports.automation_service import DailyAutomationService
from newsradar.db.models import Base
from newsradar.operations.commands import OperationCommandService
from newsradar.waves.planning import WaveMemberSnapshot, wave_plan_from_members

NOW = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)


def _plan(window_hours: int):
    return wave_plan_from_members(
        profile_id="high-value-ai-tech",
        members=(
            WaveMemberSnapshot(
                source_id="source-a",
                provider_id="provider-a",
                definition_hash="definition-a",
                roles=("evidence",),
                availability="ready",
                access_kind="rss",
                fetchable=True,
                blocked_reason=None,
            ),
        ),
        window_hours=window_hours,
        trend_days=7,
    )


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


def test_worker_does_not_catch_up_schedule_checks_after_a_long_operation(monkeypatch) -> None:
    _stub_worker_dependencies(monkeypatch, processed_results=iter([False] * 4))
    ticks = []
    monotonic_values = iter([0.0, 180.0, 180.1, 180.2])
    sleeps = 0

    monkeypatch.setattr(cli, "_tick_daily_automation", lambda: ticks.append("tick"))
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(monotonic_values))

    def fake_sleep(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 4:
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


def test_worker_consumes_operation_after_scheduled_tick_defers_active_manual_48h_run(
    tmp_path, monkeypatch
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worker-conflict.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        OperationCommandService(session, utcnow=lambda: NOW).enqueue_daily_autopilot(
            plan=_plan(48), trigger="web"
        )
        DailyAutomationRepository(session, utcnow=lambda: NOW).enable()
        session.commit()

    processed_results = iter([True])
    _stub_worker_dependencies(monkeypatch, processed_results=processed_results)
    monkeypatch.setattr(cli, "create_session", factory)
    monkeypatch.setattr(cli.time, "monotonic", iter([0.0, 1.0]).__next__)
    consumed: list[str] = []

    class Worker:
        def __init__(self, *_args, **_kwargs):
            pass

        def run_once(self, _handler):
            if consumed:
                raise _StopWorkerLoop
            consumed.append("operation")
            return True

    class FixedDailyAutomationService(DailyAutomationService):
        def __init__(self, session):
            super().__init__(
                session,
                utcnow=lambda: NOW,
                plan_factory=lambda _session, hours: _plan(hours),
            )

    from newsradar.daily_reports import automation_service

    monkeypatch.setattr(cli, "Worker", Worker)
    monkeypatch.setattr(
        automation_service, "DailyAutomationService", FixedDailyAutomationService
    )

    with pytest.raises(_StopWorkerLoop):
        cli.run_worker(once=False)

    assert consumed == ["operation"]
