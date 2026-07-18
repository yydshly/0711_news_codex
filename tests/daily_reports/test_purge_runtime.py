from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from stat import S_IFLNK

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from newsradar.daily_reports.purge_runtime import DailyReportPurgeHandler
from newsradar.daily_reports.repository import DailyReportRepository
from newsradar.daily_reports.schema import (
    DailyReportEditorialReviewDraft,
    DailyReportOverviewEditorialReviewDraft,
)
from newsradar.db.models import (
    Base,
    DailyAutopilotRunRecord,
    DailyReportAudioArtifactRecord,
    DailyReportItemEditorialReviewRecord,
    DailyReportItemRecord,
    DailyReportOverviewEditorialReviewRecord,
    DailyReportOverviewItemRecord,
    DailyReportPurgeTransitionRecord,
    DailyReportRecord,
    EventRecord,
    OperationRunRecord,
)
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus
from tests.web.test_daily_report_pages import NOW, seed_daily_report


def _factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'purge-test.sqlite3'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _migrated_factory(tmp_path: Path) -> sessionmaker[Session]:
    database_url = f"sqlite:///{(tmp_path / 'purge-migrated.sqlite3').as_posix()}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    return sessionmaker(engine, expire_on_commit=False)


def _lease(*report_ids: int) -> OperationLease:
    return OperationLease(
        9901,
        9902,
        1,
        "purge-test-worker",
        {"schema_version": 1, "report_ids": list(report_ids)},
        "daily_report_purge",
    )


def _trash(db: Session, report_id: int, *, archived: bool = True) -> None:
    report = db.get(DailyReportRecord, report_id)
    assert report is not None
    if archived:
        report.status = "archived"
        report.archived_at = NOW
    report.deleted_at = NOW
    report.purge_after = NOW + timedelta(days=30)
    db.commit()


def _audio(db: Session, report_id: int, relative_path: str) -> DailyReportAudioArtifactRecord:
    artifact = DailyReportAudioArtifactRecord(
        daily_report_id=report_id,
        rendition="decision",
        status="succeeded",
        script="synthetic purge test",
        script_sha256="a" * 64,
        model="test",
        voice_id="test",
        audio_format="mp3",
        sample_rate=32000,
        bitrate=128000,
        channel=1,
        relative_audio_path=relative_path,
    )
    db.add(artifact)
    db.commit()
    return artifact


def test_purge_removes_only_trashed_report_owned_rows_and_synthetic_audio(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path)
    audio_root = tmp_path / "audio"
    with factory() as db:
        report = seed_daily_report(db)
        report_id = report.id
        source_operation_id = report.source_operation_id
        event_ids = tuple(db.scalars(select(DailyReportItemRecord.event_id)))
        _trash(db, report_id)
        artifact = _audio(db, report_id, f"{report_id}/synthetic.mp3")
        audio_path = audio_root / artifact.relative_audio_path
        audio_path.parent.mkdir(parents=True)
        audio_path.write_bytes(b"synthetic-test-audio")
        autopilot = DailyAutopilotRunRecord(
            trigger="test",
            status="succeeded",
            stage="completed",
            window_hours=24,
            requested_scope={},
            daily_report_id=report_id,
            result_summary={"daily_report_id": report_id, "report_private_marker": "remove"},
            created_at=NOW,
            updated_at=NOW,
            finished_at=NOW,
        )
        db.add(autopilot)
        db.commit()
        autopilot_id = autopilot.id

    checkpoints: list[str] = []
    result = DailyReportPurgeHandler(factory, audio_root=audio_root)(
        _lease(report_id), checkpoints.append
    )

    with factory() as db:
        saved_autopilot = db.get(DailyAutopilotRunRecord, autopilot_id)
        assert result.status is OperationStatus.SUCCEEDED
        assert result.result_summary == {
            "requested": 1,
            "purged": 1,
            "missing": 0,
            "failed": 0,
            "failures": [],
        }
        assert db.get(DailyReportRecord, report_id) is None
        assert db.scalar(
            select(func.count()).select_from(DailyReportItemRecord).where(
                DailyReportItemRecord.daily_report_id == report_id
            )
        ) == 0
        assert db.scalar(
            select(func.count()).select_from(DailyReportOverviewItemRecord).where(
                DailyReportOverviewItemRecord.daily_report_id == report_id
            )
        ) == 0
        assert db.scalar(
            select(func.count()).select_from(DailyReportAudioArtifactRecord).where(
                DailyReportAudioArtifactRecord.daily_report_id == report_id
            )
        ) == 0
        assert all(db.get(EventRecord, event_id) is not None for event_id in event_ids)
        assert db.get(OperationRunRecord, source_operation_id) is not None
        assert saved_autopilot is not None
        assert saved_autopilot.daily_report_id is None
        assert saved_autopilot.result_summary == {"daily_report_retention": "purged"}
    assert not audio_path.exists()
    assert checkpoints == [f"before_daily_report_purge:{report_id}"]


def test_migrated_archived_report_purge_removes_populated_items_and_audio_together(
    tmp_path: Path,
) -> None:
    factory = _migrated_factory(tmp_path)
    audio_root = tmp_path / "migrated-audio"
    with factory() as db:
        repository = DailyReportRepository(db, utcnow=lambda: NOW)
        report = seed_daily_report(db)
        report_id = report.id
        repository.archive(report_id)
        item = repository.items(report_id)[0]
        with pytest.raises(IntegrityError, match="daily_report_archived_immutable"):
            item.included = False
            db.commit()
        db.rollback()
        _trash(db, report_id)
        artifact = _audio(db, report_id, f"{report_id}/migrated.mp3")
        audio_path = audio_root / artifact.relative_audio_path
        audio_path.parent.mkdir(parents=True)
        audio_path.write_bytes(b"synthetic-migrated-audio")

    result = DailyReportPurgeHandler(factory, audio_root=audio_root)(
        _lease(report_id), lambda _boundary: None
    )

    with factory() as db:
        assert result.status is OperationStatus.SUCCEEDED
        assert db.get(DailyReportRecord, report_id) is None
        assert db.scalar(
            select(func.count()).select_from(DailyReportItemRecord).where(
                DailyReportItemRecord.daily_report_id == report_id
            )
        ) == 0
        assert db.scalar(
            select(func.count()).select_from(DailyReportAudioArtifactRecord).where(
                DailyReportAudioArtifactRecord.daily_report_id == report_id
            )
        ) == 0
    assert not audio_path.exists()


def test_database_delete_guard_fails_before_irreversible_audio_unlink(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    audio_root = tmp_path / "audio"
    with factory() as db:
        repository = DailyReportRepository(db, utcnow=lambda: NOW)
        report = seed_daily_report(db)
        report_id = report.id
        repository.archive(report_id)
        _trash(db, report_id)
        artifact = _audio(db, report_id, f"{report_id}/guarded.mp3")
        audio_path = audio_root / artifact.relative_audio_path
        audio_path.parent.mkdir(parents=True)
        audio_path.write_bytes(b"synthetic-guarded-audio")
        db.execute(
            text(
                "CREATE TRIGGER test_block_report_delete "
                "BEFORE DELETE ON daily_reports BEGIN "
                "SELECT RAISE(ABORT, 'synthetic_delete_guard'); END"
            )
        )
        db.commit()

    result = DailyReportPurgeHandler(factory, audio_root=audio_root)(
        _lease(report_id), lambda _boundary: None
    )

    with factory() as db:
        assert result.status is OperationStatus.FAILED
        assert result.result_summary["failures"] == [
            {"report_id": report_id, "error_code": "daily_report_purge_persistence_failed"}
        ]
        assert db.get(DailyReportRecord, report_id) is not None
    assert audio_path.read_bytes() == b"synthetic-guarded-audio"


def test_purge_rejects_trashed_draft_before_audio_side_effects(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    audio_root = tmp_path / "audio"
    with factory() as db:
        report = seed_daily_report(db)
        report_id = report.id
        _trash(db, report_id, archived=False)
        artifact = _audio(db, report_id, f"{report_id}/draft.mp3")
        audio_path = audio_root / artifact.relative_audio_path
        audio_path.parent.mkdir(parents=True)
        audio_path.write_bytes(b"synthetic-draft-audio")

    result = DailyReportPurgeHandler(factory, audio_root=audio_root)(
        _lease(report_id), lambda _boundary: None
    )

    with factory() as db:
        assert result.status is OperationStatus.FAILED
        assert result.result_summary["failures"] == [
            {"report_id": report_id, "error_code": "daily_report_must_be_archived_for_purge"}
        ]
        assert db.get(DailyReportRecord, report_id) is not None
    assert audio_path.read_bytes() == b"synthetic-draft-audio"


def test_multiple_audio_cleanup_failure_keeps_durable_retry_without_restoring_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _factory(tmp_path)
    audio_root = tmp_path / "audio"
    with factory() as db:
        report = seed_daily_report(db)
        report_id = report.id
        _trash(db, report_id)
        first = _audio(db, report_id, f"{report_id}/first.mp3")
        second = _audio(db, report_id, f"{report_id}/second.mp3")
        first_path = audio_root / first.relative_audio_path
        second_path = audio_root / second.relative_audio_path
        first_path.parent.mkdir(parents=True)
        first_path.write_bytes(b"first")
        second_path.write_bytes(b"second")

    original_unlink = Path.unlink

    def fail_second(path: Path, *args: object, **kwargs: object) -> None:
        if path == second_path:
            raise OSError("synthetic second unlink failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_second)
    result = DailyReportPurgeHandler(factory, audio_root=audio_root)(
        _lease(report_id), lambda _boundary: None
    )

    with factory() as db:
        assert result.status is OperationStatus.FAILED
        assert result.retryable is True
        assert db.get(DailyReportRecord, report_id) is None
        assert inspect(db.bind).has_table("daily_report_audio_purge_queue")
        assert db.execute(
            text(
                "SELECT relative_audio_path FROM daily_report_audio_purge_queue "
                "WHERE daily_report_id = :report_id"
            ),
            {"report_id": report_id},
        ).scalars().all() == [second.relative_audio_path]
    assert not first_path.exists()
    assert second_path.read_bytes() == b"second"

    monkeypatch.setattr(Path, "unlink", original_unlink)
    retried = DailyReportPurgeHandler(factory, audio_root=audio_root)(
        _lease(report_id), lambda _boundary: None
    )
    with factory() as db:
        assert retried.status is OperationStatus.SUCCEEDED
        assert db.execute(
            text(
                "SELECT count(*) FROM daily_report_audio_purge_queue "
                "WHERE daily_report_id = :report_id"
            ),
            {"report_id": report_id},
        ).scalar_one() == 0
    assert not second_path.exists()


def test_database_commit_failure_occurs_before_any_audio_cleanup(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    audio_root = tmp_path / "audio"
    with factory() as db:
        report = seed_daily_report(db)
        report_id = report.id
        _trash(db, report_id)
        first = _audio(db, report_id, f"{report_id}/commit-first.mp3")
        second = _audio(db, report_id, f"{report_id}/commit-second.mp3")
        first_path = audio_root / first.relative_audio_path
        second_path = audio_root / second.relative_audio_path
        first_path.parent.mkdir(parents=True)
        first_path.write_bytes(b"first")
        second_path.write_bytes(b"second")

    def fail_commit(_session: Session) -> None:
        raise SQLAlchemyError("synthetic commit failure")

    event.listen(factory.class_, "before_commit", fail_commit)
    try:
        result = DailyReportPurgeHandler(factory, audio_root=audio_root)(
            _lease(report_id), lambda _boundary: None
        )
    finally:
        event.remove(factory.class_, "before_commit", fail_commit)

    with factory() as db:
        assert result.status is OperationStatus.FAILED
        assert db.get(DailyReportRecord, report_id) is not None
    assert first_path.read_bytes() == b"first"
    assert second_path.read_bytes() == b"second"


def test_unlink_failure_keeps_committed_report_purge_and_is_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _factory(tmp_path)
    audio_root = tmp_path / "audio"
    with factory() as db:
        report = seed_daily_report(db)
        report_id = report.id
        _trash(db, report_id)
        artifact = _audio(db, report_id, f"{report_id}/retry.mp3")
        audio_path = audio_root / artifact.relative_audio_path
        audio_path.parent.mkdir(parents=True)
        audio_path.write_bytes(b"synthetic-test-audio")

    original_unlink = Path.unlink

    def fail_synthetic_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == audio_path:
            raise OSError("synthetic unlink failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_synthetic_unlink)
    failed = DailyReportPurgeHandler(factory, audio_root=audio_root)(
        _lease(report_id), lambda _boundary: None
    )

    with factory() as db:
        assert failed.status is OperationStatus.FAILED
        assert failed.retryable is True
        assert failed.result_summary["failed"] == 1
        assert db.get(DailyReportRecord, report_id) is None
        assert db.get(DailyReportAudioArtifactRecord, artifact.id) is None
    assert audio_path.exists()

    monkeypatch.setattr(Path, "unlink", original_unlink)
    retried = DailyReportPurgeHandler(factory, audio_root=audio_root)(
        _lease(report_id), lambda _boundary: None
    )

    with factory() as db:
        assert retried.status is OperationStatus.SUCCEEDED
        assert db.get(DailyReportRecord, report_id) is None
    assert not audio_path.exists()


def test_path_escape_is_rejected_without_unlinking_or_deleting_report(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    audio_root = tmp_path / "audio"
    escaped = tmp_path / "must-survive.mp3"
    escaped.write_bytes(b"outside-root")
    with factory() as db:
        report = seed_daily_report(db)
        report_id = report.id
        _trash(db, report_id)
        _audio(db, report_id, "../must-survive.mp3")

    result = DailyReportPurgeHandler(factory, audio_root=audio_root)(
        _lease(report_id), lambda _boundary: None
    )

    with factory() as db:
        assert result.status is OperationStatus.FAILED
        assert result.retryable is False
        assert result.result_summary["failures"] == [
            {"report_id": report_id, "error_code": "daily_report_audio_path_outside_root"}
        ]
        assert db.get(DailyReportRecord, report_id) is not None
    assert escaped.read_bytes() == b"outside-root"


def test_in_root_audio_symlink_is_rejected_without_unlinking_target_or_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _factory(tmp_path)
    audio_root = tmp_path / "audio"
    report_directory = audio_root / "report-dir"
    other_report_directory = audio_root / "other-report"
    report_directory.mkdir(parents=True)
    other_report_directory.mkdir(parents=True)
    target = other_report_directory / "real.mp3"
    target.write_bytes(b"other-report-audio")
    link = report_directory / "link.mp3"
    real_symlink = True
    try:
        link.symlink_to(Path("..") / "other-report" / "real.mp3")
    except OSError as error:
        if getattr(error, "winerror", None) != 1314:
            raise
        real_symlink = False
        link.write_bytes(b"other-report-audio")
        original_lstat = Path.lstat
        original_resolve = Path.resolve
        link_stat = original_lstat(link)

        def simulated_lstat(path: Path) -> os.stat_result:
            if path == link:
                return os.stat_result((S_IFLNK | 0o777, *link_stat[1:]))
            return original_lstat(path)

        def simulated_resolve(path: Path, strict: bool = False) -> Path:
            if path == link:
                return target
            return original_resolve(path, strict=strict)

        monkeypatch.setattr(Path, "lstat", simulated_lstat)
        monkeypatch.setattr(Path, "resolve", simulated_resolve)
    with factory() as db:
        report = seed_daily_report(db)
        report_id = report.id
        _trash(db, report_id)
        artifact = _audio(db, report_id, "report-dir/link.mp3")
        artifact_id = artifact.id

    result = DailyReportPurgeHandler(factory, audio_root=audio_root)(
        _lease(report_id), lambda _boundary: None
    )

    with factory() as db:
        assert result.status is OperationStatus.FAILED
        assert result.retryable is True
        assert result.result_summary["failures"] == [
            {"report_id": report_id, "error_code": "daily_report_audio_path_symlink"}
        ]
        assert db.get(DailyReportRecord, report_id) is not None
        assert db.get(DailyReportAudioArtifactRecord, artifact_id) is not None
    assert link.exists()
    if real_symlink:
        assert link.is_symlink()
    assert link.read_bytes() == b"other-report-audio"
    assert target.read_bytes() == b"other-report-audio"


def test_member_failure_does_not_block_other_reports_and_returns_partial(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    audio_root = tmp_path / "audio"
    escaped = tmp_path / "must-survive.mp3"
    escaped.write_bytes(b"outside-root")
    with factory() as db:
        first = seed_daily_report(db, operation_id=4101)
        second = seed_daily_report(db, operation_id=4102)
        for report_id in (first.id, second.id):
            _trash(db, report_id)
        _audio(db, first.id, "../must-survive.mp3")

    result = DailyReportPurgeHandler(factory, audio_root=audio_root)(
        _lease(first.id, second.id), lambda _boundary: None
    )

    with factory() as db:
        assert result.status is OperationStatus.PARTIAL
        assert result.result_summary["purged"] == 1
        assert result.result_summary["failed"] == 1
        assert db.get(DailyReportRecord, first.id) is not None
        assert db.get(DailyReportRecord, second.id) is None


def test_persistence_failure_does_not_block_later_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _factory(tmp_path)
    with factory() as db:
        first = seed_daily_report(db, operation_id=4101)
        second = seed_daily_report(db, operation_id=4102)
        for report_id in (first.id, second.id):
            _trash(db, report_id)
        first_id, second_id = first.id, second.id

    original_delete = DailyReportPurgeHandler._delete_owned_rows
    failed_once = False

    def fail_first(session: Session, report_id: int) -> None:
        nonlocal failed_once
        if report_id == first_id and not failed_once:
            failed_once = True
            raise SQLAlchemyError("synthetic persistence failure")
        original_delete(session, report_id)

    monkeypatch.setattr(DailyReportPurgeHandler, "_delete_owned_rows", staticmethod(fail_first))
    result = DailyReportPurgeHandler(factory, audio_root=tmp_path / "audio")(
        _lease(first_id, second_id), lambda _boundary: None
    )

    with factory() as db:
        assert result.status is OperationStatus.PARTIAL
        assert result.retryable is True
        assert result.result_summary["failures"] == [
            {"report_id": first_id, "error_code": "daily_report_purge_persistence_failed"}
        ]
        assert db.get(DailyReportRecord, first_id) is not None
        assert db.get(DailyReportRecord, second_id) is None


def test_purging_middle_revision_reparents_newer_and_detaches_external_refs(
    tmp_path: Path,
) -> None:
    factory = _migrated_factory(tmp_path)
    with factory() as db:
        repository = DailyReportRepository(db, utcnow=lambda: NOW)
        original = seed_daily_report(db)
        repository.archive(original.id)
        middle = repository.revise(original.id)
        middle_item = repository.items(middle.id)[0]
        middle_overview = repository.overview_items(middle.id)[0]
        repository.save_editorial_review(
            middle.id,
            middle_item.id,
            DailyReportEditorialReviewDraft.create(
                decision="keep",
                zh_title="middle",
                zh_summary="middle",
                review_recommendation="middle",
                evidence_assessment="middle",
            ),
        )
        repository.save_overview_editorial_review(
            middle.id,
            middle_overview.id,
            DailyReportOverviewEditorialReviewDraft.create(
                decision="keep",
                zh_title="middle",
                zh_summary="middle",
                review_recommendation="middle",
                evidence_assessment="middle",
            ),
        )
        repository.archive(middle.id)
        newer = repository.revise(middle.id)
        newer_id = newer.id
        middle_id = middle.id
        original_id = original.id
        newer_review = db.scalar(
            select(DailyReportItemEditorialReviewRecord)
            .join(DailyReportItemRecord)
            .where(DailyReportItemRecord.daily_report_id == newer_id)
        )
        newer_overview_review = db.scalar(
            select(DailyReportOverviewEditorialReviewRecord)
            .join(
                DailyReportOverviewItemRecord,
                DailyReportOverviewEditorialReviewRecord.daily_report_overview_item_id
                == DailyReportOverviewItemRecord.id,
            )
            .where(DailyReportOverviewItemRecord.daily_report_id == newer_id)
        )
        assert newer_review is not None
        assert newer_overview_review is not None
        newer_overview_review.duplicate_of_overview_item_id = middle_overview.id
        db.commit()
        repository.archive(newer_id)
        newest = repository.revise(newer_id)
        repository.archive(newest.id)
        newest_id = newest.id
        newer_review_id = newer_review.id
        newer_overview_review_id = newer_overview_review.id
        _trash(db, middle_id)

    result = DailyReportPurgeHandler(factory, audio_root=tmp_path / "audio")(
        _lease(middle_id), lambda _boundary: None
    )

    with factory() as db:
        newer = db.get(DailyReportRecord, newer_id)
        newer_review = db.get(DailyReportItemEditorialReviewRecord, newer_review_id)
        newer_overview_review = db.get(
            DailyReportOverviewEditorialReviewRecord, newer_overview_review_id
        )
        assert result.status is OperationStatus.SUCCEEDED
        assert newer is not None
        assert newer.supersedes_report_id == original_id
        newest = db.get(DailyReportRecord, newest_id)
        assert newest is not None
        assert newest.supersedes_report_id == newer_id
        assert newer_review is not None
        assert newer_review.copied_from_editorial_review_id is None
        assert newer_overview_review is not None
        assert newer_overview_review.copied_from_editorial_review_id is None
        assert newer_overview_review.duplicate_of_overview_item_id is None


def test_migrated_guard_rejects_forged_archived_reparent_transition(
    tmp_path: Path,
) -> None:
    factory = _migrated_factory(tmp_path)
    with factory() as db:
        repository = DailyReportRepository(db, utcnow=lambda: NOW)
        original = seed_daily_report(db)
        repository.archive(original.id)
        middle = repository.revise(original.id)
        repository.archive(middle.id)
        newer = repository.revise(middle.id)
        repository.archive(newer.id)
        _trash(db, middle.id)
        unrelated = seed_daily_report(
            db,
            report_date=NOW.date() + timedelta(days=1),
            operation_id=4201,
        )
        repository.archive(unrelated.id)

        with pytest.raises(IntegrityError, match="daily_report_archived_immutable"):
            db.add(
                DailyReportPurgeTransitionRecord(
                    child_report_id=newer.id,
                    deleted_parent_id=middle.id,
                    predecessor_report_id=original.id,
                    temporary_parent_id=unrelated.id,
                )
            )
            db.flush()
            db.execute(
                update(DailyReportRecord)
                .where(DailyReportRecord.id == newer.id)
                .values(supersedes_report_id=unrelated.id)
            )
            db.commit()


def test_migrated_guard_rejects_committing_valid_incomplete_transition(
    tmp_path: Path,
) -> None:
    factory = _migrated_factory(tmp_path)
    with factory() as db:
        repository = DailyReportRepository(db, utcnow=lambda: NOW)
        original = seed_daily_report(db)
        repository.archive(original.id)
        middle = repository.revise(original.id)
        repository.archive(middle.id)
        newer = repository.revise(middle.id)
        repository.archive(newer.id)
        _trash(db, middle.id)

        with pytest.raises(IntegrityError):
            db.add(
                DailyReportPurgeTransitionRecord(
                    child_report_id=newer.id,
                    deleted_parent_id=middle.id,
                    predecessor_report_id=original.id,
                    temporary_parent_id=newer.id,
                )
            )
            db.flush()
            db.execute(
                update(DailyReportRecord)
                .where(DailyReportRecord.id == newer.id)
                .values(supersedes_report_id=newer.id)
            )
            db.commit()


def test_migrated_transition_barrier_cannot_be_armed(tmp_path: Path) -> None:
    factory = _migrated_factory(tmp_path)

    with factory() as db:
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    "INSERT INTO daily_report_purge_transition_barrier (id) VALUES (1)"
                )
            )
            db.commit()


def test_missing_report_is_an_idempotent_success(tmp_path: Path) -> None:
    factory = _factory(tmp_path)

    result = DailyReportPurgeHandler(factory, audio_root=tmp_path / "audio")(
        _lease(999999), lambda _boundary: None
    )

    assert result.status is OperationStatus.SUCCEEDED
    assert result.result_summary["missing"] == 1


def test_handler_rechecks_report_is_still_trashed(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as db:
        report = seed_daily_report(db)
        report_id = report.id

    result = DailyReportPurgeHandler(factory, audio_root=tmp_path / "audio")(
        _lease(report_id), lambda _boundary: None
    )

    with factory() as db:
        assert result.status is OperationStatus.FAILED
        assert result.retryable is False
        assert result.result_summary["failures"] == [
            {"report_id": report_id, "error_code": "daily_report_must_be_trashed_for_purge"}
        ]
        assert db.get(DailyReportRecord, report_id) is not None


def test_handler_rechecks_report_has_no_new_active_work(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as db:
        report = seed_daily_report(db)
        report_id = report.id
        _trash(db, report_id)
        db.add(
            OperationRunRecord(
                operation_type="daily_report_audio",
                trigger="test",
                status="running",
                requested_scope={"daily_report_id": report_id, "rendition": "decision"},
                result_summary={},
                created_at=NOW,
            )
        )
        db.commit()

    result = DailyReportPurgeHandler(factory, audio_root=tmp_path / "audio")(
        _lease(report_id), lambda _boundary: None
    )

    with factory() as db:
        assert result.status is OperationStatus.FAILED
        assert result.retryable is True
        assert result.result_summary["failures"] == [
            {"report_id": report_id, "error_code": "daily_report_has_active_work"}
        ]
        assert db.get(DailyReportRecord, report_id) is not None
