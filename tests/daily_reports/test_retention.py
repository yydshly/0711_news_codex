from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.daily_reports.repository import DailyReportRepository
from newsradar.daily_reports.retention import (
    RETENTION_DAYS,
    TRASH_BATCH_LIMIT,
    TRASH_DAYS,
    RetentionActionResult,
)
from newsradar.db.models import (
    Base,
    DailyAutopilotRunRecord,
    DailyReportAudioArtifactRecord,
    DailyReportRecord,
    OperationRunRecord,
)
from newsradar.web.daily_report_queries import DailyReportQueryService

NOW = datetime(2026, 7, 16, 4, tzinfo=UTC)


def _sqlite_timestamp(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _report(
    session: Session, *, report_date: date, report_id: int | None = None
) -> DailyReportRecord:
    operation_id = 10_000 + (report_id or report_date.day)
    session.add(
        OperationRunRecord(
            id=operation_id,
            operation_type="event_pipeline",
            trigger="test",
            status="succeeded",
            requested_scope={},
            result_summary={},
            created_at=NOW,
            finished_at=NOW,
        )
    )
    session.flush()
    report = DailyReportRecord(
        id=report_id,
        report_date=report_date,
        timezone="UTC",
        window_hours=24,
        window_start=NOW - timedelta(days=1),
        window_end=NOW,
        source_operation_id=operation_id,
        status="archived",
        revision=1,
        generation_summary={},
        generated_at=NOW,
        archived_at=NOW,
    )
    session.add(report)
    session.commit()
    return report


def _revision_record(
    session: Session,
    template: DailyReportRecord,
    *,
    revision: int,
    supersedes_report_id: int | None,
    deleted_at: datetime | None = None,
) -> DailyReportRecord:
    report = DailyReportRecord(
        report_date=template.report_date,
        timezone=template.timezone,
        window_hours=template.window_hours,
        window_start=template.window_start,
        window_end=template.window_end,
        source_operation_id=template.source_operation_id,
        status="archived",
        revision=revision,
        supersedes_report_id=supersedes_report_id,
        generation_summary={},
        generated_at=NOW,
        archived_at=NOW,
        deleted_at=deleted_at,
        purge_after=(
            deleted_at + timedelta(days=TRASH_DAYS) if deleted_at is not None else None
        ),
    )
    session.add(report)
    session.commit()
    return report


def test_retention_constants_and_result_are_stable() -> None:
    result = RetentionActionResult(17, "pinned", "日报已置顶。")

    assert (RETENTION_DAYS, TRASH_DAYS, TRASH_BATCH_LIMIT) == (90, 30, 50)
    assert result.report_id == 17
    with pytest.raises(AttributeError):
        result.outcome = "trashed"  # type: ignore[misc]


def test_pin_unpin_and_manual_trash_keep_pin_and_set_recovery_window(
    db_session: Session,
) -> None:
    report = _report(db_session, report_date=date(2026, 4, 16))
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)

    assert repository.pin(report.id).outcome == "pinned"
    trashed = repository.move_to_trash(report.id)
    stored = db_session.get(DailyReportRecord, report.id)

    assert trashed == RetentionActionResult(report.id, "trashed", "日报已移入回收站。")
    assert stored is not None
    assert stored.pinned_at == _sqlite_timestamp(NOW)
    assert stored.deleted_at == _sqlite_timestamp(NOW)
    assert stored.purge_after == _sqlite_timestamp(NOW + timedelta(days=TRASH_DAYS))
    assert repository.restore(report.id).outcome == "restored"
    assert stored.deleted_at is None
    assert stored.purge_after is None
    assert stored.pinned_at == _sqlite_timestamp(NOW)
    assert repository.unpin(report.id).outcome == "unpinned"


def test_restore_blocks_trashed_successor_when_active_sibling_exists(
    db_session: Session,
) -> None:
    parent = _report(db_session, report_date=date(2026, 7, 14))
    abandoned = _revision_record(
        db_session,
        parent,
        revision=2,
        supersedes_report_id=parent.id,
        deleted_at=NOW,
    )
    _revision_record(
        db_session,
        parent,
        revision=3,
        supersedes_report_id=parent.id,
    )
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    before = (abandoned.deleted_at, abandoned.purge_after)

    result = repository.restore(abandoned.id)

    assert result == RetentionActionResult(
        abandoned.id,
        "blocked",
        "该日报已有新的有效修订版，不能直接恢复。",
    )
    assert (abandoned.deleted_at, abandoned.purge_after) == before


def test_restore_blocks_trashed_root_when_newer_active_root_exists(
    db_session: Session,
) -> None:
    abandoned = _report(db_session, report_date=date(2026, 7, 14))
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    repository.move_to_trash(abandoned.id)
    _revision_record(
        db_session,
        abandoned,
        revision=2,
        supersedes_report_id=None,
    )
    before = (abandoned.deleted_at, abandoned.purge_after)

    result = repository.restore(abandoned.id)

    assert result == RetentionActionResult(
        abandoned.id,
        "blocked",
        "该日报已有新的有效修订版，不能直接恢复。",
    )
    assert (abandoned.deleted_at, abandoned.purge_after) == before


def test_trash_candidates_exclude_pinned_and_limit_to_old_active_reports(
    db_session: Session,
) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    old = _report(
        db_session,
        report_date=(NOW - timedelta(days=RETENTION_DAYS)).date(),
        report_id=1,
    )
    pinned = _report(
        db_session,
        report_date=(NOW - timedelta(days=RETENTION_DAYS + 1)).date(),
        report_id=2,
    )
    recent = _report(
        db_session,
        report_date=(NOW - timedelta(days=RETENTION_DAYS - 1)).date(),
        report_id=3,
    )
    pinned.pinned_at = NOW
    db_session.commit()

    candidates = repository.trash_candidates()

    assert tuple(candidate.id for candidate in candidates) == (old.id,)
    assert recent.id not in {candidate.id for candidate in candidates}


def test_automatic_trash_rechecks_pin_after_candidate_selection(
    db_session: Session,
) -> None:
    report = _report(
        db_session,
        report_date=(NOW - timedelta(days=RETENTION_DAYS)).date(),
    )
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)

    assert tuple(candidate.id for candidate in repository.trash_candidates()) == (report.id,)
    repository.pin(report.id)

    result = repository.move_to_trash(report.id, automatic=True)

    assert result == RetentionActionResult(
        report.id,
        "unchanged",
        "日报已置顶，自动清理已跳过。",
    )
    stored = db_session.get(DailyReportRecord, report.id)
    assert stored is not None
    assert stored.deleted_at is None


def test_retention_and_period_windows_use_shanghai_local_date(
    db_session: Session,
) -> None:
    shanghai_morning = datetime(2026, 7, 16, 23, 30, tzinfo=UTC)
    repository = DailyReportRepository(db_session, utcnow=lambda: shanghai_morning)
    candidate = _report(db_session, report_date=date(2026, 4, 18), report_id=1)
    too_recent = _report(db_session, report_date=date(2026, 4, 19), report_id=2)
    seven_day_edge = _report(db_session, report_date=date(2026, 7, 11), report_id=3)
    seven_day_expired = _report(db_session, report_date=date(2026, 7, 10), report_id=4)
    thirty_day_edge = _report(db_session, report_date=date(2026, 6, 18), report_id=5)
    thirty_day_expired = _report(db_session, report_date=date(2026, 6, 17), report_id=6)

    candidates = repository.trash_candidates()
    queries = DailyReportQueryService(db_session)

    assert tuple(row.id for row in candidates) == (candidate.id,)
    assert too_recent.id not in {row.id for row in candidates}
    assert tuple(
        row.report_id for row in queries.list_reports(period="7", now=shanghai_morning)
    ) == (seven_day_edge.id,)
    assert tuple(
        row.report_id for row in queries.list_reports(period="30", now=shanghai_morning)
    ) == (seven_day_edge.id, seven_day_expired.id, thirty_day_edge.id)
    assert seven_day_expired.id not in {
        row.report_id for row in queries.list_reports(period="7", now=shanghai_morning)
    }
    assert thirty_day_expired.id not in {
        row.report_id for row in queries.list_reports(period="30", now=shanghai_morning)
    }


@pytest.mark.parametrize(
    ("activity", "expected_diagnostic"),
    (
        ("autopilot", "自动日报仍在处理中，完成或取消后才能删除。"),
        ("audio", "日报语音仍在处理中，完成或取消后才能删除。"),
        ("purge", "日报清理仍在处理中，完成或取消后才能删除。"),
    ),
)
def test_manual_trash_blocks_active_report_work_with_safe_chinese_diagnostic(
    db_session: Session, activity: str, expected_diagnostic: str
) -> None:
    report = _report(db_session, report_date=date(2026, 4, 16))
    if activity == "autopilot":
        db_session.add(
            DailyAutopilotRunRecord(
                trigger="test",
                status="running",
                stage="wait_audio",
                window_hours=24,
                requested_scope={},
                daily_report_id=report.id,
                result_summary={},
                created_at=NOW,
                updated_at=NOW,
            )
        )
    else:
        operation = OperationRunRecord(
            operation_type=("daily_report_audio" if activity == "audio" else "daily_report_purge"),
            trigger="test",
            status="queued",
            requested_scope=(
                {"daily_report_id": report.id}
                if activity == "purge"
                else {"artifact": "daily-report"}
            ),
            result_summary={},
            created_at=NOW,
        )
        db_session.add(operation)
        db_session.flush()
        if activity == "audio":
            db_session.add(
                DailyReportAudioArtifactRecord(
                    daily_report_id=report.id,
                    rendition="decision",
                    status="queued",
                    script="安全文稿",
                    script_sha256="0" * 64,
                    model="test",
                    voice_id="test",
                    audio_format="mp3",
                    sample_rate=24_000,
                    bitrate=64_000,
                    channel=1,
                    operation_run_id=operation.id,
                )
            )
    db_session.commit()

    result = DailyReportRepository(db_session, utcnow=lambda: NOW).move_to_trash(report.id)

    stored = db_session.get(DailyReportRecord, report.id)
    assert result == RetentionActionResult(report.id, "blocked", expected_diagnostic)
    assert stored is not None
    assert stored.deleted_at is None
    assert stored.purge_after is None


def test_manual_trash_blocks_queued_audio_operation_before_artifact_exists(
    db_session: Session,
) -> None:
    report = _report(db_session, report_date=date(2026, 4, 16))
    db_session.add(
        OperationRunRecord(
            operation_type="daily_report_audio",
            trigger="test",
            status="queued",
            requested_scope={"daily_report_id": report.id, "rendition": "decision"},
            result_summary={},
            created_at=NOW,
        )
    )
    db_session.commit()

    result = DailyReportRepository(db_session, utcnow=lambda: NOW).move_to_trash(report.id)

    assert result == RetentionActionResult(
        report.id,
        "blocked",
        "日报语音仍在处理中，完成或取消后才能删除。",
    )


def test_report_queries_isolate_trashed_reports_and_offer_trash_views(
    db_session: Session,
) -> None:
    active = _report(db_session, report_date=date(2026, 7, 16), report_id=1)
    pinned = _report(db_session, report_date=date(2026, 7, 15), report_id=2)
    trashed = _report(db_session, report_date=date(2026, 7, 14), report_id=3)
    purges_first = _report(db_session, report_date=date(2026, 7, 13), report_id=4)
    pinned.pinned_at = NOW
    trashed.deleted_at = NOW
    trashed.purge_after = NOW + timedelta(days=TRASH_DAYS)
    purges_first.deleted_at = NOW - timedelta(days=5)
    purges_first.purge_after = NOW + timedelta(days=1)
    db_session.commit()
    queries = DailyReportQueryService(db_session)

    assert tuple(row.report_id for row in queries.list_reports(period="all")) == (
        active.id,
        pinned.id,
    )
    assert tuple(row.report_id for row in queries.list_reports(period="pinned")) == (pinned.id,)
    assert queries.detail(trashed.id) is None
    assert tuple(
        row.report_id for row in queries.trash_reports(page=1, page_size=10)
    ) == (purges_first.id, trashed.id)
    state = queries.trash_state(trashed.id)
    assert state is not None
    assert state.report_id == trashed.id
    assert state.deleted_at == _sqlite_timestamp(NOW)
    assert state.purge_after == _sqlite_timestamp(NOW + timedelta(days=TRASH_DAYS))
