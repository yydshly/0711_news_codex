from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from newsradar.daily_reports.repository import DailyReportRepository
from newsradar.daily_reports.schema import (
    DailyReportDraft,
    DailyReportItemDraft,
    ReportSection,
)
from newsradar.db.models import (
    Base,
    DailyReportRecord,
    EventRecord,
    OperationRunRecord,
)

NOW = datetime(2026, 7, 16, 4, tzinfo=UTC)


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _draft(session: Session, *, report_date: date = date(2026, 7, 16)) -> DailyReportDraft:
    operation_id = int(report_date.strftime("%m%d"))
    if session.get(OperationRunRecord, operation_id) is None:
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
    base_event_id = operation_id * 10
    for event_id, status in (
        (base_event_id + 1, "confirmed"),
        (base_event_id + 2, "emerging"),
        (base_event_id + 3, "emerging"),
    ):
        if session.get(EventRecord, event_id) is None:
            session.add(
                EventRecord(
                    id=event_id,
                    canonical_key=f"daily-report-test-{event_id}",
                    status=status,
                    current_version_number=1,
                    occurred_at=NOW,
                )
            )
    session.commit()
    return DailyReportDraft(
        report_date=report_date,
        window_hours=24,
        window_start=NOW - timedelta(hours=24),
        window_end=NOW,
        source_operation_id=operation_id,
        generation_summary={"confirmed_count": 1, "emerging_count": 2},
        items=tuple(
            DailyReportItemDraft(
                event_id=event_id,
                event_version_number=1,
                section=ReportSection(status),
                position=position,
                snapshot={"zh_title": f"事件 {event_id}", "status": status},
            )
            for event_id, status, position in (
                (base_event_id + 1, "confirmed", 1),
                (base_event_id + 2, "emerging", 1),
                (base_event_id + 3, "emerging", 2),
            )
        ),
    )


def test_create_draft_is_idempotent_while_same_draft_exists(db_session: Session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    first = repository.create_draft(_draft(db_session))
    second = repository.create_draft(_draft(db_session))
    assert second.id == first.id
    assert db_session.scalar(select(func.count()).select_from(DailyReportRecord)) == 1


def test_draft_can_toggle_and_move_only_inside_its_section(db_session: Session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    report = repository.create_draft(_draft(db_session))
    confirmed, first_signal, second_signal = repository.items(report.id)

    repository.set_included(report.id, first_signal.id, included=False)
    repository.move_item(report.id, second_signal.id, direction="up")

    rows = repository.items(report.id)
    assert [row.event_id for row in rows if row.section == "confirmed"] == [confirmed.event_id]
    assert [row.event_id for row in rows if row.section == "emerging"] == [
        second_signal.event_id,
        first_signal.event_id,
    ]
    assert next(row for row in rows if row.id == first_signal.id).included is False


def test_archived_report_rejects_mutation_and_revision_copies_snapshots(
    db_session: Session,
) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original = repository.create_draft(_draft(db_session))
    archived = repository.archive(original.id)

    with pytest.raises(ValueError, match="daily_report_archived"):
        repository.set_included(
            archived.id, repository.items(archived.id)[0].id, included=False
        )

    revision = repository.revise(archived.id)
    assert revision.status == "draft"
    assert revision.revision == archived.revision + 1
    assert revision.supersedes_report_id == archived.id
    assert [row.snapshot for row in repository.items(revision.id)] == [
        row.snapshot for row in repository.items(archived.id)
    ]


def test_repository_rejects_invalid_move_and_foreign_item(db_session: Session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    left = repository.create_draft(_draft(db_session, report_date=date(2026, 7, 16)))
    right = repository.create_draft(_draft(db_session, report_date=date(2026, 7, 17)))
    foreign_item = repository.items(right.id)[0]
    with pytest.raises(ValueError, match="invalid_daily_report_move"):
        repository.move_item(left.id, repository.items(left.id)[0].id, direction="sideways")
    with pytest.raises(LookupError, match="daily_report_item_not_found"):
        repository.set_included(left.id, foreign_item.id, included=False)


def test_repository_rejects_revision_of_draft_and_reuses_existing_revision(
    db_session: Session,
) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    draft = repository.create_draft(_draft(db_session))
    with pytest.raises(ValueError, match="daily_report_must_be_archived"):
        repository.revise(draft.id)
    archived = repository.archive(draft.id)
    first = repository.revise(archived.id)
    second = repository.revise(archived.id)
    assert second.id == first.id


def test_move_at_section_boundary_is_a_no_op(db_session: Session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    report = repository.create_draft(_draft(db_session))
    first = next(row for row in repository.items(report.id) if row.section == "emerging")
    before = [(row.id, row.position) for row in repository.items(report.id)]
    repository.move_item(report.id, first.id, direction="up")
    assert [(row.id, row.position) for row in repository.items(report.id)] == before
