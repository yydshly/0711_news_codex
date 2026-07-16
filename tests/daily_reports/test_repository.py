import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newsradar.daily_reports.repository import DailyReportRepository
from newsradar.daily_reports.schema import (
    DailyReportDraft,
    DailyReportItemDraft,
    ReportSection,
)
from newsradar.db.models import (
    Base,
    DailyReportItemRecord,
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


def _file_engine(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'daily-reports.db'}")
    Base.metadata.create_all(engine)
    return engine


def _integrity_error(*, unique: bool) -> IntegrityError:
    message = (
        "UNIQUE constraint failed: daily_reports.report_date, "
        "daily_reports.window_hours, daily_reports.revision"
        if unique
        else "FOREIGN KEY constraint failed"
    )
    original = sqlite3.IntegrityError(message)
    original.sqlite_errorcode = (
        sqlite3.SQLITE_CONSTRAINT_UNIQUE if unique else sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY
    )
    return IntegrityError("INSERT INTO daily_reports", {}, original)


def _named_unique_integrity_error(columns: str) -> IntegrityError:
    original = sqlite3.IntegrityError(f"UNIQUE constraint failed: {columns}")
    original.sqlite_errorcode = sqlite3.SQLITE_CONSTRAINT_UNIQUE
    return IntegrityError("INSERT INTO daily_reports", {}, original)


def _insert_competing_draft(session: Session, draft: DailyReportDraft) -> DailyReportRecord:
    revision = int(
        session.scalar(
            select(func.max(DailyReportRecord.revision)).where(
                DailyReportRecord.report_date == draft.report_date,
                DailyReportRecord.window_hours == draft.window_hours,
            )
        )
        or 0
    ) + 1
    report = DailyReportRecord(
        report_date=draft.report_date,
        timezone="Asia/Shanghai",
        window_hours=draft.window_hours,
        window_start=draft.window_start,
        window_end=draft.window_end,
        source_operation_id=draft.source_operation_id,
        status="draft",
        revision=revision,
        supersedes_report_id=draft.supersedes_report_id,
        generation_summary=draft.generation_summary,
        generated_at=NOW,
    )
    session.add(report)
    session.flush()
    session.add_all(
        DailyReportItemRecord(
            daily_report_id=report.id,
            event_id=item.event_id,
            event_version_number=item.event_version_number,
            section=item.section.value,
            position=item.position,
            included=item.included,
            snapshot=item.snapshot,
        )
        for item in draft.items
    )
    session.commit()
    return report


def _insert_competing_archived_revision(
    session: Session, draft: DailyReportDraft
) -> DailyReportRecord:
    report = DailyReportRecord(
        report_date=draft.report_date,
        timezone="Asia/Shanghai",
        window_hours=draft.window_hours,
        window_start=draft.window_start,
        window_end=draft.window_end,
        source_operation_id=draft.source_operation_id,
        status="archived",
        revision=1,
        supersedes_report_id=None,
        generation_summary=draft.generation_summary,
        generated_at=NOW,
        archived_at=NOW,
    )
    session.add(report)
    session.commit()
    return report


def test_create_draft_is_idempotent_while_same_draft_exists(db_session: Session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    first = repository.create_draft(_draft(db_session))
    second = repository.create_draft(_draft(db_session))
    assert second.id == first.id
    assert db_session.scalar(select(func.count()).select_from(DailyReportRecord)) == 1


def test_create_draft_reuses_same_normal_report_after_archive(db_session: Session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    draft = _draft(db_session)
    original = repository.create_draft(draft)
    archived = repository.archive(original.id)

    repeated = repository.create_draft(draft)

    assert repeated.id == archived.id
    assert repeated.status == "archived"
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
    excluded = next(row for row in repository.items(original.id) if row.section == "emerging")
    repository.set_included(original.id, excluded.id, included=False)
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
    assert [row.included for row in repository.items(revision.id)] == [True, False, True]
    assert [row.included for row in repository.items(revision.id)] == [
        row.included for row in repository.items(archived.id)
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


def test_revise_reuses_archived_direct_child_and_only_child_can_continue_chain(
    db_session: Session,
) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    parent = repository.archive(repository.create_draft(_draft(db_session)).id)
    child = repository.revise(parent.id)
    archived_child = repository.archive(child.id)

    repeated_from_parent = repository.revise(parent.id)
    grandchild = repository.revise(archived_child.id)

    assert repeated_from_parent.id == archived_child.id
    assert grandchild.supersedes_report_id == archived_child.id
    assert db_session.scalars(
        select(DailyReportRecord).where(
            DailyReportRecord.supersedes_report_id == parent.id
        )
    ).all() == [archived_child]


def test_move_at_section_boundary_is_a_no_op(db_session: Session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    report = repository.create_draft(_draft(db_session))
    first = next(row for row in repository.items(report.id) if row.section == "emerging")
    before = [(row.id, row.position) for row in repository.items(report.id)]
    repository.move_item(report.id, first.id, direction="up")
    assert [(row.id, row.position) for row in repository.items(report.id)] == before


def test_all_draft_mutations_request_the_same_report_row_lock(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    report = repository.create_draft(_draft(db_session))
    first_signal, second_signal = repository.items(report.id)[1:]
    original_scalar = db_session.scalar
    lock_flags: list[bool] = []

    def tracking_scalar(statement, *args, **kwargs):
        lock_flags.append(getattr(statement, "_for_update_arg", None) is not None)
        return original_scalar(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "scalar", tracking_scalar)

    repository.set_included(report.id, first_signal.id, included=False)
    assert lock_flags[0] is True
    lock_flags.clear()
    repository.move_item(report.id, second_signal.id, direction="up")
    assert lock_flags[0] is True
    lock_flags.clear()
    repository.archive(report.id)
    assert lock_flags[0] is True


def test_second_archive_refreshes_stale_state_and_fails(tmp_path: Path) -> None:
    engine = _file_engine(tmp_path)
    with Session(engine) as left_session, Session(engine, expire_on_commit=False) as right_session:
        left = DailyReportRepository(left_session, utcnow=lambda: NOW)
        right = DailyReportRepository(right_session, utcnow=lambda: NOW)
        report = left.create_draft(_draft(left_session))
        stale = right_session.get(DailyReportRecord, report.id)
        assert stale is not None and stale.status == "draft"
        right_session.commit()

        left.archive(report.id)

        with pytest.raises(ValueError, match="daily_report_archived"):
            right.archive(report.id)


def test_move_refreshes_positions_after_an_interleaved_move(tmp_path: Path) -> None:
    engine = _file_engine(tmp_path)
    with Session(engine) as left_session, Session(engine, expire_on_commit=False) as right_session:
        left = DailyReportRepository(left_session, utcnow=lambda: NOW)
        right = DailyReportRepository(right_session, utcnow=lambda: NOW)
        report = left.create_draft(_draft(left_session))
        stale_last = right.items(report.id)[-1]
        right_session.commit()

        left.move_item(report.id, stale_last.id, direction="up")
        rows = right.move_item(report.id, stale_last.id, direction="down")

        assert [row.event_id for row in rows if row.section == "emerging"] == [
            report.source_operation_id * 10 + 2,
            report.source_operation_id * 10 + 3,
        ]


def test_create_draft_recovers_unique_conflict_and_keeps_session_usable(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = _draft(db_session)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original_flush = db_session.flush
    original_rollback = db_session.rollback
    conflict_pending = True
    winner_id: int | None = None

    def conflicting_flush(objects=None) -> None:
        nonlocal conflict_pending
        if conflict_pending and any(isinstance(row, DailyReportRecord) for row in db_session.new):
            conflict_pending = False
            raise _integrity_error(unique=True)
        original_flush(objects)

    def rollback_with_winner() -> None:
        nonlocal winner_id
        original_rollback()
        if winner_id is None:
            with Session(db_session.get_bind()) as winning_session:
                winner_id = _insert_competing_draft(winning_session, draft).id

    monkeypatch.setattr(db_session, "flush", conflicting_flush)
    monkeypatch.setattr(db_session, "rollback", rollback_with_winner)

    report = repository.create_draft(draft)

    assert report.id == winner_id
    assert db_session.scalar(select(func.count()).select_from(DailyReportRecord)) == 1
    assert db_session.scalar(select(1)) == 1


def test_create_draft_recovers_archived_identity_conflict_and_keeps_session_usable(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = _draft(db_session)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original_flush = db_session.flush
    original_rollback = db_session.rollback
    conflict_pending = True
    winner_id: int | None = None

    def conflicting_flush(objects=None) -> None:
        nonlocal conflict_pending
        if conflict_pending and any(isinstance(row, DailyReportRecord) for row in db_session.new):
            conflict_pending = False
            raise _named_unique_integrity_error(
                "daily_reports.report_date, daily_reports.window_hours, "
                "daily_reports.source_operation_id"
            )
        original_flush(objects)

    def rollback_with_winner() -> None:
        nonlocal winner_id
        original_rollback()
        if winner_id is None:
            with Session(db_session.get_bind()) as winning_session:
                winner_id = _insert_competing_archived_revision(winning_session, draft).id

    monkeypatch.setattr(db_session, "flush", conflicting_flush)
    monkeypatch.setattr(db_session, "rollback", rollback_with_winner)

    report = repository.create_draft(draft)

    assert report.id == winner_id
    assert report.status == "archived"
    assert db_session.scalar(select(1)) == 1


def test_create_draft_recovers_direct_child_conflict_and_keeps_session_usable(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    parent = repository.archive(repository.create_draft(_draft(db_session)).id)
    child_draft = _draft(db_session)
    child_draft = DailyReportDraft(
        report_date=child_draft.report_date,
        window_hours=child_draft.window_hours,
        window_start=child_draft.window_start,
        window_end=child_draft.window_end,
        source_operation_id=child_draft.source_operation_id,
        generation_summary=child_draft.generation_summary,
        supersedes_report_id=parent.id,
        items=child_draft.items,
    )
    original_flush = db_session.flush
    original_rollback = db_session.rollback
    conflict_pending = True
    winner_id: int | None = None

    def conflicting_flush(objects=None) -> None:
        nonlocal conflict_pending
        if conflict_pending and any(isinstance(row, DailyReportRecord) for row in db_session.new):
            conflict_pending = False
            raise _named_unique_integrity_error("daily_reports.supersedes_report_id")
        original_flush(objects)

    def rollback_with_winner() -> None:
        nonlocal winner_id
        original_rollback()
        if winner_id is None:
            with Session(db_session.get_bind()) as winning_session:
                winner_id = _insert_competing_draft(winning_session, child_draft).id

    monkeypatch.setattr(db_session, "flush", conflicting_flush)
    monkeypatch.setattr(db_session, "rollback", rollback_with_winner)

    report = repository.create_draft(child_draft)

    assert report.id == winner_id
    assert report.supersedes_report_id == parent.id
    assert db_session.scalar(select(1)) == 1


def test_create_draft_retries_unique_conflicts_only_for_a_finite_time(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = _draft(db_session)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)

    def conflicting_flush(objects=None) -> None:
        if any(isinstance(row, DailyReportRecord) for row in db_session.new):
            raise _integrity_error(unique=True)

    monkeypatch.setattr(db_session, "flush", conflicting_flush)

    with pytest.raises(RuntimeError, match="daily_report_revision_conflict"):
        repository.create_draft(draft)
    assert db_session.scalar(select(1)) == 1


def test_create_draft_reuses_archived_identity_winner_after_revision_conflict(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = _draft(db_session)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original_flush = db_session.flush
    original_rollback = db_session.rollback
    conflict_pending = True
    winner_inserted = False

    def conflicting_flush(objects=None) -> None:
        nonlocal conflict_pending
        if conflict_pending and any(isinstance(row, DailyReportRecord) for row in db_session.new):
            conflict_pending = False
            raise _integrity_error(unique=True)
        original_flush(objects)

    def rollback_with_different_winner() -> None:
        nonlocal winner_inserted
        original_rollback()
        if not winner_inserted:
            winner_inserted = True
            with Session(db_session.get_bind()) as winning_session:
                _insert_competing_archived_revision(winning_session, draft)

    monkeypatch.setattr(db_session, "flush", conflicting_flush)
    monkeypatch.setattr(db_session, "rollback", rollback_with_different_winner)

    report = repository.create_draft(draft)

    assert report.status == "archived"
    assert report.revision == 1
    assert db_session.scalar(select(func.count()).select_from(DailyReportRecord)) == 1


def test_create_draft_reraises_non_unique_integrity_errors(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = _draft(db_session)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    expected = _integrity_error(unique=False)
    original_rollback = db_session.rollback
    rollback_called = False

    def conflicting_flush(objects=None) -> None:
        if any(isinstance(row, DailyReportRecord) for row in db_session.new):
            raise expected

    def tracking_rollback() -> None:
        nonlocal rollback_called
        rollback_called = True
        original_rollback()

    monkeypatch.setattr(db_session, "flush", conflicting_flush)
    monkeypatch.setattr(db_session, "rollback", tracking_rollback)

    with pytest.raises(IntegrityError) as captured:
        repository.create_draft(draft)
    assert captured.value is expected
    assert rollback_called is True
    assert db_session.scalar(select(1)) == 1
