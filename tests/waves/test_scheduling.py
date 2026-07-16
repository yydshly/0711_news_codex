from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import Base, OperationRunRecord
from newsradar.operations.commands import OperationCommandService
from newsradar.waves.scheduling import enqueue_due, wave_due


def _profile() -> SimpleNamespace:
    return SimpleNamespace(id="high-value-ai-tech")


def test_wave_due_blocks_an_active_or_recent_wave() -> None:
    now = datetime(2026, 7, 16, 8, tzinfo=UTC)
    active = SimpleNamespace(status="running", created_at=now - timedelta(hours=2))
    recent = SimpleNamespace(status="succeeded", created_at=now - timedelta(minutes=5))

    assert wave_due(_profile(), active, now=now).reason == "active_or_recent_wave"
    assert wave_due(_profile(), recent, now=now).reason == "active_or_recent_wave"


def test_enqueue_due_is_idempotent_and_never_runs_network() -> None:
    now = datetime(2026, 7, 16, 8, tzinfo=UTC)

    class Commands:
        def __init__(self) -> None:
            self.latest = None
            self.enqueued: list[tuple[object, str]] = []
            self.network_calls: list[str] = []

        def latest_high_value_wave(self, profile_id: str):
            assert profile_id == "high-value-ai-tech"
            return self.latest

        def enqueue_high_value_wave(self, *, plan, trigger: str) -> int:
            self.enqueued.append((plan, trigger))
            self.latest = SimpleNamespace(status="queued", created_at=now)
            return 41

    commands = Commands()
    plan = SimpleNamespace(profile_id="high-value-ai-tech")

    first = enqueue_due(commands, plan, now=now)
    second = enqueue_due(commands, plan, now=now)

    assert first.operation_id == 41
    assert first.reason == "due"
    assert second.operation_id is None
    assert second.reason == "active_or_recent_wave"
    assert commands.enqueued == [(plan, "enqueue_due")]
    assert commands.network_calls == []


def test_command_service_selects_latest_wave_for_the_same_profile() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                OperationRunRecord(
                    operation_type="high_value_news_wave",
                    trigger="test",
                    status="succeeded",
                    requested_scope={"profile_id": "other"},
                    result_summary={},
                ),
                OperationRunRecord(
                    operation_type="high_value_news_wave",
                    trigger="test",
                    status="partial",
                    requested_scope={"profile_id": "high-value-ai-tech"},
                    result_summary={},
                ),
            ]
        )
        session.commit()

        latest = OperationCommandService(session).latest_high_value_wave("high-value-ai-tech")

        assert latest is not None
        assert latest.requested_scope["profile_id"] == "high-value-ai-tech"
