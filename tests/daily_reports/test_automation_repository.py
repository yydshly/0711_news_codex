from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.daily_reports.automation_repository import DailyAutomationRepository
from newsradar.db.models import Base

NOW = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_get_or_create_persists_the_disabled_shanghai_singleton(db_session: Session) -> None:
    repository = DailyAutomationRepository(db_session, utcnow=lambda: NOW)

    config = repository.get_or_create()

    assert config.id == 1
    assert config.enabled is False
    assert config.timezone == "Asia/Shanghai"
    assert config.daily_time == "07:30"
    assert repository.get_or_create().id == 1


def test_lock_due_returns_today_once_then_mark_scheduled_clears_due_work(
    db_session: Session,
) -> None:
    repository = DailyAutomationRepository(db_session, utcnow=lambda: NOW)
    repository.enable()

    due = repository.lock_due()

    assert due is not None
    assert due.schedule_date == date(2026, 7, 18)
    saved = repository.mark_scheduled(due, run_id=41)
    assert saved.last_scheduled_date == date(2026, 7, 18)
    assert saved.last_run_id == 41
    assert saved.next_run_at == datetime(2026, 7, 18, 23, 30, tzinfo=UTC)
    assert repository.lock_due() is None


def test_pause_preserves_the_last_run_and_prevents_due_work(db_session: Session) -> None:
    repository = DailyAutomationRepository(db_session, utcnow=lambda: NOW)
    repository.enable()
    due = repository.lock_due()
    assert due is not None
    repository.mark_scheduled(due, run_id=41)

    paused = repository.pause()

    assert paused.enabled is False
    assert paused.last_scheduled_date == date(2026, 7, 18)
    assert paused.last_run_id == 41
    assert repository.lock_due() is None


def test_get_or_create_normalizes_sqlite_timestamp_round_trips(db_session: Session) -> None:
    repository = DailyAutomationRepository(db_session, utcnow=lambda: NOW)
    repository.enable()
    db_session.commit()
    db_session.expire_all()

    config = repository.get_or_create()

    assert config.next_run_at == datetime(2026, 7, 18, 23, 30, tzinfo=UTC)
    assert config.next_run_at.tzinfo is UTC
