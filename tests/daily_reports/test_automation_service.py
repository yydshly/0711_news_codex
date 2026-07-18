from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from newsradar.daily_reports.automation_repository import DailyAutomationRepository
from newsradar.daily_reports.automation_service import DailyAutomationService
from newsradar.daily_reports.autopilot import DailyAutopilotStage
from newsradar.db.models import (
    Base,
    DailyAutopilotRunRecord,
    DailyReportRecord,
    OperationRunRecord,
)
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


def _report(
    session: Session, *, report_id: int, report_date: datetime, trashed: bool = False
) -> DailyReportRecord:
    operation = OperationRunRecord(
        id=10_000 + report_id,
        operation_type="event_pipeline",
        trigger="test",
        status="succeeded",
        requested_scope={},
        result_summary={},
        created_at=NOW,
        finished_at=NOW,
    )
    session.add(operation)
    session.flush()
    report = DailyReportRecord(
        id=report_id,
        report_date=report_date.date(),
        timezone="Asia/Shanghai",
        window_hours=24,
        window_start=NOW - timedelta(days=1),
        window_end=NOW,
        source_operation_id=operation.id,
        status="archived",
        revision=1,
        generation_summary={},
        generated_at=NOW,
        archived_at=NOW,
        deleted_at=(NOW - timedelta(days=31) if trashed else None),
        purge_after=(NOW - timedelta(days=1) if trashed else None),
    )
    session.add(report)
    return report


def test_tick_only_enqueues_one_due_daily_autopilot_and_marks_the_schedule(
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
    assert operation.status == "queued"
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


def test_tick_rolls_back_when_plan_construction_fails(db_session: Session) -> None:
    DailyAutomationRepository(db_session, utcnow=lambda: NOW).enable()
    db_session.commit()
    service = DailyAutomationService(
        db_session,
        utcnow=lambda: NOW,
        plan_factory=lambda _session, _hours: (_ for _ in ()).throw(RuntimeError("plan failed")),
    )

    with pytest.raises(RuntimeError, match="plan failed"):
        service.tick()

    assert not db_session.in_transaction()
    assert db_session.query(DailyAutopilotRunRecord).count() == 0


def test_tick_sweeps_retention_once_per_shanghai_day_in_bounded_batches(
    db_session: Session,
) -> None:
    for report_id in range(1, 26):
        _report(
            db_session,
            report_id=report_id,
            report_date=NOW - timedelta(days=90 + report_id),
        )
    for report_id in range(26, 51):
        _report(
            db_session,
            report_id=report_id,
            report_date=NOW - timedelta(days=200 + report_id),
            trashed=True,
        )
    pinned = _report(
        db_session,
        report_id=51,
        report_date=NOW - timedelta(days=200),
    )
    pinned.pinned_at = NOW
    recent = _report(
        db_session,
        report_id=52,
        report_date=NOW - timedelta(days=89),
    )
    db_session.commit()
    service = DailyAutomationService(
        db_session,
        utcnow=lambda: NOW,
        plan_factory=lambda _session, _hours: _plan(),
    )

    first = service.tick()
    second = service.tick()

    assert first.retention.outcome == "swept"
    assert first.retention.trashed_count == 25
    assert first.retention.purge_operation_id is not None
    purge = db_session.get(OperationRunRecord, first.retention.purge_operation_id)
    assert purge is not None
    assert purge.operation_type == OperationType.DAILY_REPORT_PURGE.value
    assert purge.requested_scope["report_ids"] == list(range(26, 46))
    assert second.retention.outcome == "already_checked"
    assert db_session.query(OperationRunRecord).filter(
        OperationRunRecord.operation_type == OperationType.DAILY_REPORT_PURGE.value
    ).count() == 1
    assert all(
        db_session.get(DailyReportRecord, report_id).deleted_at is not None
        for report_id in range(1, 26)
    )
    assert db_session.get(DailyReportRecord, pinned.id).deleted_at is None
    assert db_session.get(DailyReportRecord, recent.id).deleted_at is None


@pytest.mark.parametrize(
    ("operation_type", "requested_scope"),
    (
        (
            OperationType.DAILY_REPORT_AUDIO.value,
            lambda report_id: {"daily_report_id": report_id, "rendition": "decision"},
        ),
        (
            OperationType.DAILY_REPORT_PURGE.value,
            lambda report_id: {"report_ids": [report_id]},
        ),
    ),
)
def test_tick_marks_the_daily_retention_scan_done_when_all_due_purges_have_active_work(
    db_session: Session,
    operation_type: str,
    requested_scope: object,
) -> None:
    expired = _report(
        db_session,
        report_id=1,
        report_date=NOW - timedelta(days=200),
        trashed=True,
    )
    assert callable(requested_scope)
    db_session.add(
        OperationRunRecord(
            operation_type=operation_type,
            trigger="test",
            status="queued",
            requested_scope=requested_scope(expired.id),
            result_summary={},
            created_at=NOW,
        )
    )
    DailyAutomationRepository(db_session, utcnow=lambda: NOW).enable()
    db_session.commit()
    service = DailyAutomationService(
        db_session,
        utcnow=lambda: NOW,
        plan_factory=lambda _session, _hours: _plan(),
    )

    result = service.tick()

    config = DailyAutomationRepository(db_session, utcnow=lambda: NOW).get_or_create()
    assert result.outcome == "enqueued"
    assert result.retention is not None
    assert result.retention.outcome == "swept"
    assert result.retention.trashed_count == 0
    assert result.retention.purge_operation_id is None
    assert config.last_retention_date == date(2026, 7, 18)
    assert db_session.get(DailyReportRecord, expired.id) is not None
    assert db_session.query(OperationRunRecord).filter(
        OperationRunRecord.operation_type == OperationType.DAILY_REPORT_PURGE.value,
        OperationRunRecord.trigger == "schedule",
    ).count() == 0
