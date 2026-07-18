"""Bounded durable purge for trashed daily-report data."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from newsradar.db.models import (
    DailyAutopilotRunRecord,
    DailyReportAudioArtifactRecord,
    DailyReportItemEditorialReviewRecord,
    DailyReportItemRecord,
    DailyReportOverviewEditorialReviewRecord,
    DailyReportOverviewItemRecord,
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
            with self._session_factory() as session, session.begin():
                report = session.scalar(
                    select(DailyReportRecord)
                    .where(DailyReportRecord.id == report_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if report is None:
                    return "missing"
                if report.deleted_at is None:
                    raise PurgeMemberError("daily_report_must_be_trashed_for_purge", False)
                if self._has_active_work(
                    session,
                    report_id,
                    current_operation_id=operation_id,
                ):
                    raise PurgeMemberError("daily_report_has_active_work", True)

                artifacts = tuple(
                    session.scalars(
                        select(DailyReportAudioArtifactRecord).where(
                            DailyReportAudioArtifactRecord.daily_report_id == report_id
                        )
                    )
                )
                targets = tuple(
                    self._audio_target(artifact.relative_audio_path)
                    for artifact in artifacts
                    if artifact.relative_audio_path is not None
                )
                for target in targets:
                    if target.exists():
                        target.unlink()

                self._detach_external_references(session, report)
                self._delete_owned_rows(session, report_id)
            return "purged"
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
                else "daily_report_audio_unlink_failed"
            )
            raise PurgeMemberError(
                code,
                code == "daily_report_audio_unlink_failed",
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
        if relative.is_absolute():
            raise OSError("daily_report_audio_path_outside_root")
        target = (self._audio_root / relative).resolve()
        if target == self._audio_root or not target.is_relative_to(self._audio_root):
            raise OSError("daily_report_audio_path_outside_root")
        return target

    @staticmethod
    def _detach_external_references(session: Session, report: DailyReportRecord) -> None:
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
        session.execute(
            update(DailyReportRecord)
            .where(DailyReportRecord.supersedes_report_id == report.id)
            .values(supersedes_report_id=report.supersedes_report_id)
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
        session.execute(delete(DailyReportRecord).where(DailyReportRecord.id == report_id))
