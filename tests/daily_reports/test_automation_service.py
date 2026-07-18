from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from newsradar.daily_reports.automation_repository import DailyAutomationRepository
from newsradar.daily_reports.automation_service import DailyAutomationService
from newsradar.daily_reports.autopilot import DailyAutopilotStage
from newsradar.db.models import Base, DailyAutopilotRunRecord, OperationRunRecord
from newsradar.operations.schema import OperationType
from newsradar.waves.planning import WaveMemberSnapshot, wave_plan_from_members

NOW = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _plan():
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
        window_hours=24,
        trend_days=7,
    )


def test_tick_enqueues_one_due_daily_autopilot_and_marks_the_schedule(
    db_session: Session,
) -> None:
    DailyAutomationRepository(db_session, utcnow=lambda: NOW).enable()
    factory_calls: list[int] = []
    service = DailyAutomationService(
        db_session,
        utcnow=lambda: NOW,
        plan_factory=lambda _session, hours: factory_calls.append(hours) or _plan(),
    )

    result = service.tick()

    assert result.outcome == "enqueued"
    assert result.run_id is not None
    assert factory_calls == [24]
    run = db_session.get(DailyAutopilotRunRecord, result.run_id)
    assert run is not None
    assert run.stage == DailyAutopilotStage.ENQUEUE_CONTENT_WAVE.value
    operation = db_session.scalar(
        select(OperationRunRecord).where(
            OperationRunRecord.operation_type == OperationType.DAILY_AUTOPILOT.value
        )
    )
    assert operation is not None
    config = DailyAutomationRepository(db_session, utcnow=lambda: NOW).get_or_create()
    assert config.last_run_id == result.run_id
    assert config.last_scheduled_date.isoformat() == "2026-07-18"


def test_tick_noops_after_the_same_date_is_marked_scheduled(db_session: Session) -> None:
    DailyAutomationRepository(db_session, utcnow=lambda: NOW).enable()
    service = DailyAutomationService(
        db_session,
        utcnow=lambda: NOW,
        plan_factory=lambda _session, _hours: _plan(),
    )

    first = service.tick()
    second = service.tick()

    assert first.outcome == "enqueued"
    assert second.outcome == "not_due"
    assert second.run_id is None
    assert db_session.query(DailyAutopilotRunRecord).count() == 1


def test_tick_keeps_the_due_lock_until_enqueue_and_schedule_mark_commit(
    db_session: Session,
) -> None:
    DailyAutomationRepository(db_session, utcnow=lambda: NOW).enable()
    db_session.commit()
    commits: list[str] = []
    factory_transactions: list[bool] = []
    event.listen(db_session, "after_commit", lambda _session: commits.append("commit"))
    service = DailyAutomationService(
        db_session,
        utcnow=lambda: NOW,
        plan_factory=lambda current_session, _hours: (
            factory_transactions.append(current_session.in_transaction()) or _plan()
        ),
    )

    result = service.tick()

    assert result.outcome == "enqueued"
    assert factory_transactions == [True]
    assert commits == ["commit"]
