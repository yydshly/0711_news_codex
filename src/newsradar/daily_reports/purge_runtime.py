"""Bounded durable purge for trashed daily-report data."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISLNK
from typing import Literal

from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from newsradar.db.models import (
    DailyAutopilotRunRecord,
    DailyReportAudioArtifactRecord,
    DailyReportAudioPurgeQueueRecord,
    DailyReportItemEditorialReviewRecord,
    DailyReportItemRecord,
    DailyReportOverviewEditorialReviewRecord,
    DailyReportOverviewItemRecord,
    DailyReportPurgeTransitionRecord,
    DailyReportRecord,
    OperationRunRecord,
)
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus
from newsradar.operations.worker import OperationResult

MemberOutcome = Literal["purged", "missing"]


@dataclass(frozen=True, slots=True)
class PurgeMemberError(Exception):
    code: str
    retryable: bool


class DailyReportPurgeHandler:
    """Purge only report-owned rows and audio beneath a trusted root."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        audio_root: Path = Path(".local/daily-report-audio"),
    ) -> None:
        self._session_factory = session_factory
        self._audio_root = audio_root.resolve()

    def __call__(
        self, lease: OperationLease, checkpoint: Callable[[str], None]
    ) -> OperationResult:
        try:
            report_ids = self._request_report_ids(lease)
        except ValueError as error:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code=str(error),
                error_message="日报清理任务参数无效。",
                retryable=False,
            )

        purged = 0
        missing = 0
        failures: list[dict[str, object]] = []
        retryable_failure = False
        for report_id in report_ids:
            checkpoint(f"before_daily_report_purge:{report_id}")
            try:
                outcome = self._purge_member(report_id, operation_id=lease.operation_id)
            except PurgeMemberError as error:
                failures.append({"report_id": report_id, "error_code": error.code})
                retryable_failure = retryable_failure or error.retryable
                continue
            if outcome == "purged":
                purged += 1
            else:
                missing += 1

        summary = {
            "requested": len(report_ids),
            "purged": purged,
            "missing": missing,
            "failed": len(failures),
            "failures": failures,
        }
        if not failures:
            return OperationResult(
                status=OperationStatus.SUCCEEDED,
                result_summary=summary,
                retryable=False,
            )
        status = OperationStatus.PARTIAL if purged or missing else OperationStatus.FAILED
        error_message = (
            "部分日报未能安全清理。"
            if status is OperationStatus.PARTIAL
            else "日报未能安全清理。"
        )
        return OperationResult(
            status=status,
            error_code="daily_report_purge_member_failed",
            error_message=error_message,
            result_summary=summary,
            retryable=retryable_failure,
        )

    @staticmethod
    def _request_report_ids(lease: OperationLease) -> tuple[int, ...]:
        if lease.operation_type != "daily_report_purge":
            raise ValueError("unsupported_operation_type")
        scope = lease.requested_scope
        if scope.get("schema_version") != 1 or set(scope) != {"schema_version", "report_ids"}:
            raise ValueError("invalid_daily_report_purge_scope")
        values = scope.get("report_ids")
        if not isinstance(values, list) or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in values
        ):
            raise ValueError("invalid_daily_report_purge_scope")
        report_ids = tuple(dict.fromkeys(values))
        if not 1 <= len(report_ids) <= 20 or len(report_ids) != len(values):
            raise ValueError("invalid_daily_report_purge_scope")
        return report_ids

    def _purge_member(self, report_id: int, *, operation_id: int) -> MemberOutcome:
        try:
            report_was_present = False
            had_pending_audio = False
            with self._session_factory() as session, session.begin():
                queued_audio_paths = set(
                    session.scalars(
                        select(DailyReportAudioPurgeQueueRecord.relative_audio_path).where(
                            DailyReportAudioPurgeQueueRecord.daily_report_id == report_id
                        )
                    )
                )
                had_pending_audio = bool(queued_audio_paths)
                report = session.scalar(
                    select(DailyReportRecord)
                    .where(DailyReportRecord.id == report_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if report is not None:
                    report_was_present = True
                    if report.deleted_at is None:
                        raise PurgeMemberError(
                            "daily_report_must_be_trashed_for_purge", False
                        )
                    if report.status != "archived":
                        raise PurgeMemberError(
                            "daily_report_must_be_archived_for_purge", False
                        )
                    if self._has_active_work(
                        session,
                        report_id,
                        current_operation_id=operation_id,
                    ):
                        raise PurgeMemberError("daily_report_has_active_work", True)

                    artifacts = tuple(
                        session.scalars(
                            select(DailyReportAudioArtifactRecord).where(
                                DailyReportAudioArtifactRecord.daily_report_id
                                == report_id
                            )
                        )
                    )
                    audio_paths = tuple(
                        artifact.relative_audio_path
                        for artifact in artifacts
                        if artifact.relative_audio_path is not None
                    )
                    for relative_audio_path in audio_paths:
                        self._validate_audio_target(relative_audio_path)
                        if relative_audio_path not in queued_audio_paths:
                            session.add(
                                DailyReportAudioPurgeQueueRecord(
                                    daily_report_id=report_id,
                                    relative_audio_path=relative_audio_path,
                                )
                            )
                            queued_audio_paths.add(relative_audio_path)
                    predecessor_id = report.supersedes_report_id
                    reparent_report_ids = self._detach_external_references(session, report)
                    self._delete_owned_rows(session, report_id)
                    self._finish_revision_reparent(
                        session,
                        reparent_report_ids,
                        predecessor_id=predecessor_id,
                    )
                    session.flush()
                    if session.scalar(
                        select(DailyReportRecord.id).where(
                            DailyReportRecord.id == report_id
                        )
                    ) is not None:
                        raise PurgeMemberError(
                            "daily_report_purge_persistence_failed", True
                        )
            if report_was_present or had_pending_audio:
                self._cleanup_staged_audio(report_id)
                return "purged"
            return "missing"
        except PurgeMemberError:
            raise
        except SQLAlchemyError as error:
            raise PurgeMemberError(
                "daily_report_purge_persistence_failed",
                True,
            ) from error
        except OSError as error:
            code = (
                "daily_report_audio_path_outside_root"
                if str(error) == "daily_report_audio_path_outside_root"
                else (
                    "daily_report_audio_path_symlink"
                    if str(error) == "daily_report_audio_path_symlink"
                    else "daily_report_audio_unlink_failed"
                )
            )
            raise PurgeMemberError(
                code,
                code in {
                    "daily_report_audio_path_symlink",
                    "daily_report_audio_unlink_failed",
                },
            ) from error

    @staticmethod
    def _has_active_work(
        session: Session,
        report_id: int,
        *,
        current_operation_id: int,
    ) -> bool:
        if session.scalar(
            select(DailyAutopilotRunRecord.id).where(
                DailyAutopilotRunRecord.daily_report_id == report_id,
                DailyAutopilotRunRecord.status.in_(("queued", "running")),
            )
        ) is not None:
            return True
        if session.scalar(
            select(DailyReportAudioArtifactRecord.id).where(
                DailyReportAudioArtifactRecord.daily_report_id == report_id,
                DailyReportAudioArtifactRecord.status.in_(("queued", "running")),
            )
        ) is not None:
            return True
        operations = session.scalars(
            select(OperationRunRecord).where(
                OperationRunRecord.id != current_operation_id,
                OperationRunRecord.operation_type.in_(
                    ("daily_report_audio", "daily_report_purge")
                ),
                OperationRunRecord.status.in_(("queued", "running")),
            )
        )
        for operation in operations:
            scope = operation.requested_scope
            if not isinstance(scope, dict):
                continue
            if scope.get("daily_report_id") == report_id:
                return True
            values = scope.get("report_ids")
            if isinstance(values, list) and report_id in values:
                return True
        return False

    def _audio_target(self, relative_audio_path: str) -> Path:
        relative = Path(relative_audio_path)
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise OSError("daily_report_audio_path_outside_root")
        target = self._audio_root.joinpath(*relative.parts)
        if target == self._audio_root or not target.is_relative_to(self._audio_root):
            raise OSError("daily_report_audio_path_outside_root")
        return target

    def _validate_audio_target(self, relative_audio_path: str) -> Path:
        target = self._audio_target(relative_audio_path)
        current = self._audio_root
        for part in target.relative_to(self._audio_root).parts:
            current /= part
            try:
                path_stat = current.lstat()
            except FileNotFoundError:
                return target
            reparse_point = bool(
                (getattr(path_stat, "st_file_attributes", 0) or 0) & 0x400
            )
            if S_ISLNK(path_stat.st_mode) or reparse_point:
                raise OSError("daily_report_audio_path_symlink")
        return target

    def _unlink_audio(self, relative_audio_path: str) -> None:
        target = self._validate_audio_target(relative_audio_path)
        # Keep validation adjacent to unlink. The lexical target is never
        # resolved, so a final-component link introduced after lstat would be
        # unlinked as a link rather than followed to another report's file.
        try:
            target.unlink()
        except FileNotFoundError:
            return

    def _cleanup_staged_audio(self, report_id: int) -> None:
        with self._session_factory() as session:
            queued_audio = tuple(
                session.execute(
                    select(
                        DailyReportAudioPurgeQueueRecord.id,
                        DailyReportAudioPurgeQueueRecord.relative_audio_path,
                    )
                    .where(
                        DailyReportAudioPurgeQueueRecord.daily_report_id == report_id
                    )
                    .order_by(DailyReportAudioPurgeQueueRecord.id)
                )
            )
        for queue_id, relative_audio_path in queued_audio:
            self._unlink_audio(relative_audio_path)
            with self._session_factory() as session, session.begin():
                session.execute(
                    delete(DailyReportAudioPurgeQueueRecord).where(
                        DailyReportAudioPurgeQueueRecord.id == queue_id
                    )
                )

    @staticmethod
    def _detach_external_references(
        session: Session, report: DailyReportRecord
    ) -> tuple[int, ...]:
        item_ids = tuple(
            session.scalars(
                select(DailyReportItemRecord.id).where(
                    DailyReportItemRecord.daily_report_id == report.id
                )
            )
        )
        overview_item_ids = tuple(
            session.scalars(
                select(DailyReportOverviewItemRecord.id).where(
                    DailyReportOverviewItemRecord.daily_report_id == report.id
                )
            )
        )
        item_review_ids = (
            tuple(
                session.scalars(
                    select(DailyReportItemEditorialReviewRecord.id).where(
                        DailyReportItemEditorialReviewRecord.daily_report_item_id.in_(item_ids)
                    )
                )
            )
            if item_ids
            else ()
        )
        overview_review_ids = (
            tuple(
                session.scalars(
                    select(DailyReportOverviewEditorialReviewRecord.id).where(
                        DailyReportOverviewEditorialReviewRecord.daily_report_overview_item_id.in_(
                            overview_item_ids
                        )
                    )
                )
            )
            if overview_item_ids
            else ()
        )
        reparent_reports = tuple(
            session.scalars(
                select(DailyReportRecord).where(
                    DailyReportRecord.supersedes_report_id == report.id
                ).order_by(DailyReportRecord.id)
            )
        )
        DailyReportPurgeHandler._raise_on_active_revision_conflict(
            session, report, reparent_reports
        )
        reparent_report_ids = tuple(child.id for child in reparent_reports)
        if reparent_report_ids:
            for child in reparent_reports:
                temporary_parent_id = DailyReportPurgeHandler._temporary_parent_id(
                    session, child.id
                )
                transition = DailyReportPurgeTransitionRecord(
                    child_report_id=child.id,
                    deleted_parent_id=report.id,
                    predecessor_report_id=report.supersedes_report_id,
                    temporary_parent_id=temporary_parent_id,
                    barrier_id=1,
                )
                session.add(transition)
                session.flush()
                persisted = session.get(DailyReportPurgeTransitionRecord, child.id)
                if (
                    persisted is None
                    or persisted.deleted_parent_id != report.id
                    or persisted.predecessor_report_id != report.supersedes_report_id
                    or persisted.temporary_parent_id != temporary_parent_id
                ):
                    raise PurgeMemberError(
                        "daily_report_purge_persistence_failed", True
                    )
            for child in reparent_reports:
                transition = session.get(DailyReportPurgeTransitionRecord, child.id)
                if transition is None:
                    raise PurgeMemberError("daily_report_purge_persistence_failed", True)
                updated = session.execute(
                    update(DailyReportRecord)
                    .where(
                        DailyReportRecord.id == child.id,
                        DailyReportRecord.supersedes_report_id == report.id,
                    )
                    .values(supersedes_report_id=transition.temporary_parent_id)
                )
                if updated.rowcount != 1:
                    raise PurgeMemberError(
                        "daily_report_purge_persistence_failed", True
                    )
        if item_review_ids:
            session.execute(
                update(DailyReportItemEditorialReviewRecord)
                .where(
                    DailyReportItemEditorialReviewRecord.copied_from_editorial_review_id.in_(
                        item_review_ids
                    )
                )
                .values(copied_from_editorial_review_id=None)
            )
        if overview_review_ids:
            session.execute(
                update(DailyReportOverviewEditorialReviewRecord)
                .where(
                    DailyReportOverviewEditorialReviewRecord.copied_from_editorial_review_id.in_(
                        overview_review_ids
                    )
                )
                .values(copied_from_editorial_review_id=None)
            )
        if overview_item_ids:
            session.execute(
                update(DailyReportOverviewEditorialReviewRecord)
                .where(
                    DailyReportOverviewEditorialReviewRecord.duplicate_of_overview_item_id.in_(
                        overview_item_ids
                    )
                )
                .values(duplicate_of_overview_item_id=None)
            )
        autopilots = tuple(
            session.scalars(
                select(DailyAutopilotRunRecord).where(
                    DailyAutopilotRunRecord.daily_report_id == report.id
                )
            )
        )
        for autopilot in autopilots:
            autopilot.daily_report_id = None
            autopilot.result_summary = {"daily_report_retention": "purged"}
        return reparent_report_ids

    @staticmethod
    def _raise_on_active_revision_conflict(
        session: Session,
        report: DailyReportRecord,
        reparent_reports: tuple[DailyReportRecord, ...],
    ) -> None:
        active_children = tuple(
            child for child in reparent_reports if child.deleted_at is None
        )
        if not active_children:
            return
        if len(active_children) != 1:
            raise PurgeMemberError(
                "daily_report_purge_active_revision_conflict", False
            )
        active_child = active_children[0]
        if report.supersedes_report_id is not None:
            conflict_id = session.scalar(
                select(DailyReportRecord.id).where(
                    DailyReportRecord.supersedes_report_id
                    == report.supersedes_report_id,
                    DailyReportRecord.deleted_at.is_(None),
                )
            )
        else:
            conflict_id = session.scalar(
                select(DailyReportRecord.id).where(
                    DailyReportRecord.supersedes_report_id.is_(None),
                    DailyReportRecord.deleted_at.is_(None),
                    DailyReportRecord.report_date == active_child.report_date,
                    DailyReportRecord.window_hours == active_child.window_hours,
                    DailyReportRecord.source_operation_id
                    == active_child.source_operation_id,
                )
            )
        if conflict_id is not None:
            raise PurgeMemberError(
                "daily_report_purge_active_revision_conflict", False
            )

    @staticmethod
    def _temporary_parent_id(session: Session, child_report_id: int) -> int:
        child = session.execute(
            select(DailyReportRecord.id, DailyReportRecord.deleted_at).where(
                DailyReportRecord.id == child_report_id
            )
        ).one_or_none()
        if child is None:
            raise PurgeMemberError("daily_report_purge_persistence_failed", True)

        pending_report_ids = [child_report_id]
        discovered_report_ids = {child_report_id}
        deleted_at_by_report_id = {child_report_id: child.deleted_at}
        terminal_report_ids: list[int] = []
        while pending_report_ids:
            current_report_id = pending_report_ids.pop()
            descendants = tuple(
                session.execute(
                    select(DailyReportRecord.id, DailyReportRecord.deleted_at)
                    .where(
                        DailyReportRecord.supersedes_report_id == current_report_id
                    )
                    .order_by(DailyReportRecord.id)
                )
            )
            if not descendants:
                terminal_report_ids.append(current_report_id)
                continue
            for descendant_id, deleted_at in descendants:
                if descendant_id in discovered_report_ids:
                    raise PurgeMemberError(
                        "daily_report_purge_persistence_failed", True
                    )
                discovered_report_ids.add(descendant_id)
                deleted_at_by_report_id[descendant_id] = deleted_at
                pending_report_ids.append(descendant_id)

        if not terminal_report_ids:
            raise PurgeMemberError("daily_report_purge_persistence_failed", True)
        return min(
            terminal_report_ids,
            key=lambda report_id: (
                deleted_at_by_report_id[report_id] is not None,
                report_id,
            ),
        )

    @staticmethod
    def _finish_revision_reparent(
        session: Session,
        report_ids: tuple[int, ...],
        *,
        predecessor_id: int | None,
    ) -> None:
        if not report_ids:
            return
        for report_id in report_ids:
            transition = session.get(DailyReportPurgeTransitionRecord, report_id)
            if transition is None or transition.predecessor_report_id != predecessor_id:
                raise PurgeMemberError("daily_report_purge_persistence_failed", True)
            updated = session.execute(
                update(DailyReportRecord)
                .where(
                    DailyReportRecord.id == report_id,
                    DailyReportRecord.supersedes_report_id
                    == transition.temporary_parent_id,
                )
                .values(supersedes_report_id=predecessor_id)
            )
            if updated.rowcount != 1:
                raise PurgeMemberError("daily_report_purge_persistence_failed", True)
        deleted_transitions = session.execute(
            delete(DailyReportPurgeTransitionRecord).where(
                DailyReportPurgeTransitionRecord.child_report_id.in_(report_ids)
            )
        )
        if deleted_transitions.rowcount != len(report_ids):
            raise PurgeMemberError("daily_report_purge_persistence_failed", True)

    @staticmethod
    def _delete_owned_rows(session: Session, report_id: int) -> None:
        item_ids = tuple(
            session.scalars(
                select(DailyReportItemRecord.id).where(
                    DailyReportItemRecord.daily_report_id == report_id
                )
            )
        )
        overview_item_ids = tuple(
            session.scalars(
                select(DailyReportOverviewItemRecord.id).where(
                    DailyReportOverviewItemRecord.daily_report_id == report_id
                )
            )
        )
        deleted_report = session.execute(
            delete(DailyReportRecord).where(DailyReportRecord.id == report_id)
        )
        if deleted_report.rowcount != 1:
            raise PurgeMemberError("daily_report_purge_persistence_failed", True)
        if overview_item_ids:
            session.execute(
                delete(DailyReportOverviewEditorialReviewRecord).where(
                    DailyReportOverviewEditorialReviewRecord.daily_report_overview_item_id.in_(
                        overview_item_ids
                    )
                )
            )
            session.execute(
                delete(DailyReportOverviewItemRecord).where(
                    DailyReportOverviewItemRecord.id.in_(overview_item_ids)
                )
            )
        if item_ids:
            session.execute(
                delete(DailyReportItemEditorialReviewRecord).where(
                    DailyReportItemEditorialReviewRecord.daily_report_item_id.in_(item_ids)
                )
            )
            session.execute(
                delete(DailyReportItemRecord).where(DailyReportItemRecord.id.in_(item_ids))
            )
        session.execute(
            delete(DailyReportAudioArtifactRecord).where(
                DailyReportAudioArtifactRecord.daily_report_id == report_id
            )
        )
