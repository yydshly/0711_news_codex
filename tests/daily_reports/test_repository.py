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
    DailyReportEditorialReviewDraft,
    DailyReportItemDraft,
    DailyReportOverviewEditorialReviewDraft,
    DailyReportOverviewItemDraft,
    ReportSection,
)
from newsradar.db.models import (
    Base,
    DailyReportItemRecord,
    DailyReportOverviewEditorialReviewRecord,
    DailyReportOverviewItemRecord,
    DailyReportRecord,
    EventRecord,
    OperationRunRecord,
)

NOW = datetime(2026, 7, 16, 4, tzinfo=UTC)

REVIEW_KEEP = DailyReportEditorialReviewDraft.create(
    decision="keep",
    zh_title="人工标题",
    zh_summary="人工中文概述",
    review_recommendation="建议保留并继续补证",
    evidence_assessment="已有公开证据，仍需补充独立来源。",
)
REVIEW_DUPLICATE = DailyReportEditorialReviewDraft.create(
    decision="duplicate",
    zh_title="重复标题",
    zh_summary="重复概述",
    review_recommendation="与已收录条目合并去重",
    evidence_assessment="指向同一原始发布事实。",
)

OVERVIEW_KEEP = DailyReportOverviewEditorialReviewDraft.create(
    decision="keep",
    zh_title="全览人工标题",
    zh_summary="全览人工中文概述",
    review_recommendation="继续跟踪第一方后续",
    evidence_assessment="已有第一方公开证据。",
)
OVERVIEW_NEEDS_EVIDENCE = DailyReportOverviewEditorialReviewDraft.create(
    decision="needs_evidence",
    zh_title="全览待补证标题",
    zh_summary="全览待补证概述",
    review_recommendation="寻找第二条独立证据",
    evidence_assessment="目前只有单一来源。",
)


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
        overview_items=tuple(
            DailyReportOverviewItemDraft(
                event_id=event_id,
                event_version_number=1,
                position=position,
                snapshot={"zh_title": f"全览事件 {event_id}", "status": status},
                decision_event_id=event_id,
            )
            for position, (event_id, status) in enumerate(
                (
                    (base_event_id + 1, "confirmed"),
                    (base_event_id + 2, "emerging"),
                    (base_event_id + 3, "emerging"),
                ),
                start=1,
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


def test_save_editorial_review_appends_history_syncs_inclusion_and_preserves_snapshot(
    db_session: Session,
) -> None:
    report = DailyReportRepository(db_session, utcnow=lambda: NOW).create_draft(
        _draft(db_session)
    )
    item = DailyReportRepository(db_session).items(report.id)[1]
    before = dict(item.snapshot)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)

    first = repository.save_editorial_review(report.id, item.id, REVIEW_KEEP)
    second = repository.save_editorial_review(report.id, item.id, REVIEW_DUPLICATE)

    assert (first.revision, second.revision) == (1, 2)
    assert [row.decision for row in repository.editorial_reviews(item.id)] == [
        "keep",
        "duplicate",
    ]
    assert db_session.get(DailyReportItemRecord, item.id).included is False
    assert db_session.get(DailyReportItemRecord, item.id).snapshot == before


def test_save_editorial_review_rejects_archived_report(db_session: Session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    report = repository.create_draft(_draft(db_session))
    item = repository.items(report.id)[0]
    repository.archive(report.id)

    with pytest.raises(ValueError, match="daily_report_archived"):
        repository.save_editorial_review(report.id, item.id, REVIEW_KEEP)


def test_save_editorial_review_rejects_foreign_item(db_session: Session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    left = repository.create_draft(_draft(db_session, report_date=date(2026, 7, 16)))
    right = repository.create_draft(_draft(db_session, report_date=date(2026, 7, 17)))
    foreign_item = repository.items(right.id)[0]

    with pytest.raises(LookupError, match="daily_report_item_not_found"):
        repository.save_editorial_review(left.id, foreign_item.id, REVIEW_KEEP)


def test_save_overview_review_appends_history_preserves_snapshot_and_reports_readiness(
    db_session: Session,
) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    report = repository.create_draft(_draft(db_session))
    first_item, reviewed_item, _unreviewed_item = repository.overview_items(report.id)
    before = dict(reviewed_item.snapshot)

    first = repository.save_overview_editorial_review(
        report.id, reviewed_item.id, OVERVIEW_KEEP
    )
    duplicate = DailyReportOverviewEditorialReviewDraft.create(
        decision="duplicate",
        zh_title="重复全览标题",
        zh_summary="与主条目相同",
        review_recommendation="合并到主条目",
        evidence_assessment="原始 URL 和发布时间相同。",
        duplicate_of_overview_item_id=first_item.id,
    )
    second = repository.save_overview_editorial_review(
        report.id, reviewed_item.id, duplicate
    )
    repository.save_overview_editorial_review(
        report.id, first_item.id, OVERVIEW_NEEDS_EVIDENCE
    )

    assert (first.revision, second.revision) == (1, 2)
    assert [
        row.decision for row in repository.overview_editorial_reviews(reviewed_item.id)
    ] == ["keep", "duplicate"]
    assert db_session.get(DailyReportOverviewItemRecord, reviewed_item.id).snapshot == before
    readiness = repository.overview_audio_readiness(report.id)
    assert readiness.total_count == 3
    assert readiness.reviewed_count == 2
    assert readiness.included_count == 1


def test_save_overview_review_rejects_foreign_self_and_archived_targets(
    db_session: Session,
) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    left = repository.create_draft(_draft(db_session, report_date=date(2026, 7, 16)))
    right = repository.create_draft(_draft(db_session, report_date=date(2026, 7, 17)))
    left_item, left_target, _ = repository.overview_items(left.id)
    foreign_target = repository.overview_items(right.id)[0]

    for target, code in (
        (left_item.id, "invalid_daily_report_overview_duplicate_self"),
        (foreign_target.id, "invalid_daily_report_overview_duplicate_target"),
    ):
        draft = DailyReportOverviewEditorialReviewDraft.create(
            decision="duplicate",
            zh_title="重复标题",
            zh_summary="重复概述",
            review_recommendation="合并",
            evidence_assessment="相同事实",
            duplicate_of_overview_item_id=target,
        )
        with pytest.raises(ValueError, match=code):
            repository.save_overview_editorial_review(left.id, left_item.id, draft)

    foreign_item = repository.overview_items(right.id)[1]
    with pytest.raises(LookupError, match="daily_report_overview_item_not_found"):
        repository.save_overview_editorial_review(left.id, foreign_item.id, OVERVIEW_KEEP)

    repository.archive(left.id)
    with pytest.raises(ValueError, match="daily_report_archived"):
        repository.save_overview_editorial_review(left.id, left_target.id, OVERVIEW_KEEP)


def test_revise_copies_latest_overview_review_and_remaps_duplicate_target(
    db_session: Session,
) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original = repository.create_draft(_draft(db_session))
    target, duplicate_item, _ = repository.overview_items(original.id)
    repository.save_overview_editorial_review(
        original.id, duplicate_item.id, OVERVIEW_KEEP
    )
    latest = repository.save_overview_editorial_review(
        original.id,
        duplicate_item.id,
        DailyReportOverviewEditorialReviewDraft.create(
            decision="duplicate",
            zh_title="最新重复标题",
            zh_summary="最新重复概述",
            review_recommendation="与主事件合并",
            evidence_assessment="相同第一方链接。",
            duplicate_of_overview_item_id=target.id,
        ),
    )
    repository.archive(original.id)

    revision = repository.revise(original.id)
    copied_by_event = {
        item.event_id: item for item in repository.overview_items(revision.id)
    }
    copied_item = copied_by_event[duplicate_item.event_id]
    copied_review = repository.overview_editorial_reviews(copied_item.id)[0]

    assert copied_review.revision == 1
    assert copied_review.decision == "duplicate"
    assert copied_review.zh_title == "最新重复标题"
    assert copied_review.copied_from_editorial_review_id == latest.id
    assert copied_review.duplicate_of_overview_item_id == copied_by_event[target.event_id].id


def test_revise_copies_only_latest_editorial_review_without_mutating_history(
    db_session: Session,
) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original = repository.create_draft(_draft(db_session))
    original_item = repository.items(original.id)[1]
    first = repository.save_editorial_review(original.id, original_item.id, REVIEW_KEEP)
    latest = repository.save_editorial_review(original.id, original_item.id, REVIEW_DUPLICATE)
    repository.archive(original.id)

    revision = repository.revise(original.id)
    copied_item = next(
        item for item in repository.items(revision.id) if item.event_id == original_item.event_id
    )
    copied_reviews = repository.editorial_reviews(copied_item.id)

    assert [(row.id, row.revision) for row in repository.editorial_reviews(original_item.id)] == [
        (first.id, 1),
        (latest.id, 2),
    ]
    assert len(copied_reviews) == 1
    assert copied_reviews[0].revision == 1
    assert copied_reviews[0].decision == latest.decision
    assert copied_reviews[0].zh_title == latest.zh_title
    assert copied_reviews[0].copied_from_editorial_review_id == latest.id


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


def test_archive_rejects_latest_corrupted_overview_review_and_keeps_draft(
    db_session: Session,
) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    report = repository.create_draft(_draft(db_session))
    item = repository.overview_items(report.id)[0]
    db_session.add(
        DailyReportOverviewEditorialReviewRecord(
            daily_report_overview_item_id=item.id,
            revision=1,
            decision="keep",
            zh_title="中文标题",
            zh_summary="中文概述。",
            review_recommendation="????",
            evidence_assessment="当前证据可供审核。",
            created_at=NOW,
        )
    )
    db_session.commit()

    with pytest.raises(ValueError, match="daily_report_text_corrupted"):
        repository.archive(report.id)

    assert db_session.get(DailyReportRecord, report.id).status == "draft"


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
