from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

from sqlalchemy import case, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newsradar.daily_reports.schema import (
    REPORT_TIMEZONE,
    DailyReportDraft,
    DailyReportItemDraft,
    ReportSection,
    ReportStatus,
    validate_window_hours,
)
from newsradar.db.models import DailyReportItemRecord, DailyReportRecord

MAX_REVISION_ATTEMPTS = 3


class DailyReportRepository:
    def __init__(
        self,
        session: Session,
        *,
        utcnow: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self._utcnow = utcnow or (lambda: datetime.now(UTC))

    def create_draft(self, draft: DailyReportDraft) -> DailyReportRecord:
        validate_window_hours(draft.window_hours)
        for attempt in range(MAX_REVISION_ATTEMPTS):
            self._lock_revision(draft.report_date, draft.window_hours)
            existing = self._matching_draft(draft)
            if existing is not None:
                self.session.commit()
                return existing

            revision = int(
                self.session.scalar(
                    select(func.max(DailyReportRecord.revision)).where(
                        DailyReportRecord.report_date == draft.report_date,
                        DailyReportRecord.window_hours == draft.window_hours,
                    )
                )
                or 0
            ) + 1
            report = DailyReportRecord(
                report_date=draft.report_date,
                timezone=REPORT_TIMEZONE,
                window_hours=draft.window_hours,
                window_start=draft.window_start,
                window_end=draft.window_end,
                source_operation_id=draft.source_operation_id,
                status=ReportStatus.DRAFT.value,
                revision=revision,
                supersedes_report_id=draft.supersedes_report_id,
                generation_summary=draft.generation_summary,
                generated_at=self._utcnow(),
            )
            try:
                self.session.add(report)
                self.session.flush()
                self.session.add_all(
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
                self.session.commit()
                return report
            except IntegrityError as error:
                self.session.rollback()
                if not self._is_revision_conflict(error):
                    raise
                existing = self._matching_draft(draft)
                if existing is not None:
                    self.session.commit()
                    return existing
                self.session.rollback()
                if attempt == MAX_REVISION_ATTEMPTS - 1:
                    raise RuntimeError("daily_report_revision_conflict") from error

        raise RuntimeError("daily_report_revision_conflict")

    def items(self, report_id: int) -> tuple[DailyReportItemRecord, ...]:
        records = self.session.scalars(
            select(DailyReportItemRecord)
            .where(DailyReportItemRecord.daily_report_id == report_id)
            .order_by(
                case((DailyReportItemRecord.section == "confirmed", 0), else_=1),
                DailyReportItemRecord.position,
                DailyReportItemRecord.id,
            )
            .execution_options(populate_existing=True)
        )
        return tuple(records)

    def set_included(
        self,
        report_id: int,
        item_id: int,
        *,
        included: bool,
    ) -> DailyReportItemRecord:
        self._draft_report(report_id)
        item = self._owned_item(report_id, item_id)
        item.included = included
        self.session.commit()
        return item

    def move_item(
        self,
        report_id: int,
        item_id: int,
        *,
        direction: str,
    ) -> tuple[DailyReportItemRecord, ...]:
        if direction not in {"up", "down"}:
            raise ValueError("invalid_daily_report_move")
        self._draft_report(report_id)
        item = self._owned_item(report_id, item_id)
        section_rows = [row for row in self.items(report_id) if row.section == item.section]
        index = next(index for index, row in enumerate(section_rows) if row.id == item.id)
        target_index = index - 1 if direction == "up" else index + 1
        if target_index < 0 or target_index >= len(section_rows):
            rows = self.items(report_id)
            self.session.commit()
            return rows

        adjacent = section_rows[target_index]
        item_position, adjacent_position = item.position, adjacent.position
        temporary_position = max(row.position for row in section_rows) + 1
        item.position = temporary_position
        self.session.flush()
        adjacent.position = item_position
        self.session.flush()
        item.position = adjacent_position
        self.session.commit()
        return self.items(report_id)

    def archive(self, report_id: int) -> DailyReportRecord:
        report = self._draft_report(report_id)
        report.status = ReportStatus.ARCHIVED.value
        report.archived_at = self._utcnow()
        self.session.commit()
        return report

    def revise(self, report_id: int) -> DailyReportRecord:
        original = self.session.get(DailyReportRecord, report_id)
        if original is None:
            raise LookupError("daily_report_not_found")
        if original.status != ReportStatus.ARCHIVED.value:
            raise ValueError("daily_report_must_be_archived")
        return self.create_draft(
            DailyReportDraft(
                report_date=original.report_date,
                window_hours=original.window_hours,
                window_start=original.window_start,
                window_end=original.window_end,
                source_operation_id=original.source_operation_id,
                generation_summary=dict(original.generation_summary),
                supersedes_report_id=original.id,
                items=tuple(
                    DailyReportItemDraft(
                        event_id=row.event_id,
                        event_version_number=row.event_version_number,
                        section=ReportSection(row.section),
                        position=row.position,
                        snapshot=dict(row.snapshot),
                        included=row.included,
                    )
                    for row in self.items(original.id)
                ),
            )
        )

    def _lock_revision(self, report_date: date, window_hours: int) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            return
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"newsradar:daily-report:{report_date.isoformat()}:{window_hours}"},
        )

    def _draft_report(self, report_id: int) -> DailyReportRecord:
        report = self.session.scalar(
            select(DailyReportRecord)
            .where(DailyReportRecord.id == report_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if report is None:
            self.session.rollback()
            raise LookupError("daily_report_not_found")
        if report.status != ReportStatus.DRAFT.value:
            self.session.rollback()
            raise ValueError("daily_report_archived")
        return report

    def _owned_item(self, report_id: int, item_id: int) -> DailyReportItemRecord:
        item = self.session.scalar(
            select(DailyReportItemRecord).where(
                DailyReportItemRecord.id == item_id,
                DailyReportItemRecord.daily_report_id == report_id,
            )
        )
        if item is None:
            self.session.rollback()
            raise LookupError("daily_report_item_not_found")
        return item

    def _matching_draft(self, draft: DailyReportDraft) -> DailyReportRecord | None:
        return self.session.scalar(
            select(DailyReportRecord).where(
                DailyReportRecord.report_date == draft.report_date,
                DailyReportRecord.window_hours == draft.window_hours,
                DailyReportRecord.source_operation_id == draft.source_operation_id,
                DailyReportRecord.status == ReportStatus.DRAFT.value,
                DailyReportRecord.supersedes_report_id == draft.supersedes_report_id,
            )
        )

    @staticmethod
    def _is_revision_conflict(error: IntegrityError) -> bool:
        original = error.orig
        diagnostics = getattr(original, "diag", None)
        constraint_name = getattr(diagnostics, "constraint_name", None)
        if constraint_name is not None:
            return constraint_name == "uq_daily_report_revision"

        sqlite_errorcode = getattr(original, "sqlite_errorcode", None)
        if sqlite_errorcode not in {1555, 2067}:
            return False
        return (
            "daily_reports.report_date, daily_reports.window_hours, daily_reports.revision"
            in str(original)
        )
