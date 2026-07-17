from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import case, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newsradar.daily_reports.schema import (
    REPORT_TIMEZONE,
    DailyReportDraft,
    DailyReportEditorialReviewDraft,
    DailyReportItemDraft,
    DailyReportOverviewEditorialReviewDraft,
    DailyReportOverviewItemDraft,
    EditorialDecision,
    ReportSection,
    ReportStatus,
    validate_window_hours,
)
from newsradar.db.models import (
    DailyReportItemEditorialReviewRecord,
    DailyReportItemRecord,
    DailyReportOverviewEditorialReviewRecord,
    DailyReportOverviewItemRecord,
    DailyReportRecord,
)

MAX_REVISION_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class OverviewAudioReadiness:
    total_count: int
    reviewed_count: int
    included_count: int


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
            existing = self._matching_report(draft)
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
                decision_items = [
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
                ]
                self.session.add_all(decision_items)
                self.session.flush()
                decision_by_event = {
                    (item.event_id, item.event_version_number): item
                    for item in decision_items
                }
                self.session.add_all(
                    DailyReportOverviewItemRecord(
                        daily_report_id=report.id,
                        event_id=item.event_id,
                        event_version_number=item.event_version_number,
                        position=item.position,
                        snapshot=item.snapshot,
                        decision_item_id=(
                            decision_by_event[
                                (item.decision_event_id, item.event_version_number)
                            ].id
                            if item.decision_event_id is not None
                            else None
                        ),
                    )
                    for item in draft.overview_items
                )
                self.session.commit()
                return report
            except IntegrityError as error:
                self.session.rollback()
                if not self._is_revision_conflict(error):
                    raise
                existing = self._matching_report(draft)
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

    def overview_items(
        self, report_id: int
    ) -> tuple[DailyReportOverviewItemRecord, ...]:
        return tuple(
            self.session.scalars(
                select(DailyReportOverviewItemRecord)
                .where(DailyReportOverviewItemRecord.daily_report_id == report_id)
                .order_by(
                    DailyReportOverviewItemRecord.position,
                    DailyReportOverviewItemRecord.id,
                )
                .execution_options(populate_existing=True)
            )
        )

    def save_overview_editorial_review(
        self,
        report_id: int,
        item_id: int,
        draft: DailyReportOverviewEditorialReviewDraft,
    ) -> DailyReportOverviewEditorialReviewRecord:
        self._draft_report(report_id)
        item = self._owned_overview_item(report_id, item_id)
        duplicate_target_id = draft.duplicate_of_overview_item_id
        if duplicate_target_id == item.id:
            self.session.rollback()
            raise ValueError("invalid_daily_report_overview_duplicate_self")
        if duplicate_target_id is not None:
            target = self.session.scalar(
                select(DailyReportOverviewItemRecord).where(
                    DailyReportOverviewItemRecord.id == duplicate_target_id,
                    DailyReportOverviewItemRecord.daily_report_id == report_id,
                )
            )
            if target is None:
                self.session.rollback()
                raise ValueError("invalid_daily_report_overview_duplicate_target")
        revision = int(
            self.session.scalar(
                select(func.max(DailyReportOverviewEditorialReviewRecord.revision)).where(
                    DailyReportOverviewEditorialReviewRecord.daily_report_overview_item_id
                    == item.id
                )
            )
            or 0
        ) + 1
        review = DailyReportOverviewEditorialReviewRecord(
            daily_report_overview_item_id=item.id,
            revision=revision,
            decision=draft.decision.value,
            zh_title=draft.zh_title,
            zh_summary=draft.zh_summary,
            review_recommendation=draft.review_recommendation,
            evidence_assessment=draft.evidence_assessment,
            duplicate_of_overview_item_id=duplicate_target_id,
            created_at=self._utcnow(),
        )
        self.session.add(review)
        self.session.commit()
        return review

    def overview_editorial_reviews(
        self, item_id: int
    ) -> tuple[DailyReportOverviewEditorialReviewRecord, ...]:
        return tuple(
            self.session.scalars(
                select(DailyReportOverviewEditorialReviewRecord)
                .where(
                    DailyReportOverviewEditorialReviewRecord.daily_report_overview_item_id
                    == item_id
                )
                .order_by(
                    DailyReportOverviewEditorialReviewRecord.revision,
                    DailyReportOverviewEditorialReviewRecord.id,
                )
            )
        )

    def overview_audio_readiness(self, report_id: int) -> OverviewAudioReadiness:
        items = self.overview_items(report_id)
        if not items:
            return OverviewAudioReadiness(0, 0, 0)
        latest: dict[int, DailyReportOverviewEditorialReviewRecord] = {}
        for review in self.session.scalars(
            select(DailyReportOverviewEditorialReviewRecord)
            .where(
                DailyReportOverviewEditorialReviewRecord.daily_report_overview_item_id.in_(
                    tuple(item.id for item in items)
                )
            )
            .order_by(
                DailyReportOverviewEditorialReviewRecord.daily_report_overview_item_id,
                DailyReportOverviewEditorialReviewRecord.revision.desc(),
                DailyReportOverviewEditorialReviewRecord.id.desc(),
            )
        ):
            latest.setdefault(review.daily_report_overview_item_id, review)
        return OverviewAudioReadiness(
            total_count=len(items),
            reviewed_count=len(latest),
            included_count=sum(
                review.decision
                in {EditorialDecision.KEEP.value, EditorialDecision.NEEDS_EVIDENCE.value}
                for review in latest.values()
            ),
        )

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

    def save_editorial_review(
        self,
        report_id: int,
        item_id: int,
        draft: DailyReportEditorialReviewDraft,
    ) -> DailyReportItemEditorialReviewRecord:
        self._draft_report(report_id)
        item = self._owned_item(report_id, item_id)
        revision = int(
            self.session.scalar(
                select(func.max(DailyReportItemEditorialReviewRecord.revision)).where(
                    DailyReportItemEditorialReviewRecord.daily_report_item_id == item.id
                )
            )
            or 0
        ) + 1
        review = DailyReportItemEditorialReviewRecord(
            daily_report_item_id=item.id,
            revision=revision,
            decision=draft.decision.value,
            zh_title=draft.zh_title,
            zh_summary=draft.zh_summary,
            review_recommendation=draft.review_recommendation,
            evidence_assessment=draft.evidence_assessment,
            created_at=self._utcnow(),
        )
        item.included = draft.decision in {
            EditorialDecision.KEEP,
            EditorialDecision.NEEDS_EVIDENCE,
        }
        self.session.add(review)
        self.session.commit()
        return review

    def editorial_reviews(
        self, item_id: int
    ) -> tuple[DailyReportItemEditorialReviewRecord, ...]:
        return tuple(
            self.session.scalars(
                select(DailyReportItemEditorialReviewRecord)
                .where(DailyReportItemEditorialReviewRecord.daily_report_item_id == item_id)
                .order_by(
                    DailyReportItemEditorialReviewRecord.revision,
                    DailyReportItemEditorialReviewRecord.id,
                )
            )
        )

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

    def archive(self, report_id: int, *, commit: bool = True) -> DailyReportRecord:
        report = self._draft_report(report_id)
        report.status = ReportStatus.ARCHIVED.value
        report.archived_at = self._utcnow()
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return report

    def revise(
        self,
        report_id: int,
        *,
        legacy_overview_items: tuple[DailyReportOverviewItemDraft, ...] = (),
    ) -> DailyReportRecord:
        original = self.session.get(DailyReportRecord, report_id)
        if original is None:
            raise LookupError("daily_report_not_found")
        if original.status != ReportStatus.ARCHIVED.value:
            raise ValueError("daily_report_must_be_archived")
        original_overview_items = self.overview_items(original.id)
        overview_items = (
            tuple(
                DailyReportOverviewItemDraft(
                    event_id=row.event_id,
                    event_version_number=row.event_version_number,
                    position=row.position,
                    snapshot=dict(row.snapshot),
                    decision_event_id=(
                        row.event_id if row.decision_item_id is not None else None
                    ),
                )
                for row in original_overview_items
            )
            if original_overview_items
            else legacy_overview_items
        )
        revision = self.create_draft(
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
                overview_items=overview_items,
            )
        )
        for original_item, revision_item in zip(
            self.items(original.id), self.items(revision.id), strict=True
        ):
            latest_review = self._latest_editorial_review(original_item.id)
            if latest_review is None or self._latest_editorial_review(revision_item.id) is not None:
                continue
            self.session.add(
                DailyReportItemEditorialReviewRecord(
                    daily_report_item_id=revision_item.id,
                    revision=1,
                    decision=latest_review.decision,
                    zh_title=latest_review.zh_title,
                    zh_summary=latest_review.zh_summary,
                    review_recommendation=latest_review.review_recommendation,
                    evidence_assessment=latest_review.evidence_assessment,
                    copied_from_editorial_review_id=latest_review.id,
                    created_at=self._utcnow(),
                )
            )
        original_overview_by_event = {
            (row.event_id, row.event_version_number): row
            for row in self.overview_items(original.id)
        }
        revision_overview_by_event = {
            (row.event_id, row.event_version_number): row
            for row in self.overview_items(revision.id)
        }
        for event_key, original_item in original_overview_by_event.items():
            revision_item = revision_overview_by_event.get(event_key)
            if revision_item is None:
                continue
            latest_review = self._latest_overview_editorial_review(original_item.id)
            if (
                latest_review is None
                or self._latest_overview_editorial_review(revision_item.id) is not None
            ):
                continue
            duplicate_target_id = None
            if latest_review.duplicate_of_overview_item_id is not None:
                original_target = self.session.get(
                    DailyReportOverviewItemRecord,
                    latest_review.duplicate_of_overview_item_id,
                )
                if original_target is None:
                    raise ValueError("invalid_daily_report_overview_duplicate_target")
                revision_target = revision_overview_by_event.get(
                    (original_target.event_id, original_target.event_version_number)
                )
                if revision_target is None:
                    raise ValueError("invalid_daily_report_overview_duplicate_target")
                duplicate_target_id = revision_target.id
            self.session.add(
                DailyReportOverviewEditorialReviewRecord(
                    daily_report_overview_item_id=revision_item.id,
                    revision=1,
                    decision=latest_review.decision,
                    zh_title=latest_review.zh_title,
                    zh_summary=latest_review.zh_summary,
                    review_recommendation=latest_review.review_recommendation,
                    evidence_assessment=latest_review.evidence_assessment,
                    duplicate_of_overview_item_id=duplicate_target_id,
                    copied_from_editorial_review_id=latest_review.id,
                    created_at=self._utcnow(),
                )
            )
        self.session.commit()
        return revision

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

    def _owned_overview_item(
        self, report_id: int, item_id: int
    ) -> DailyReportOverviewItemRecord:
        item = self.session.scalar(
            select(DailyReportOverviewItemRecord).where(
                DailyReportOverviewItemRecord.id == item_id,
                DailyReportOverviewItemRecord.daily_report_id == report_id,
            )
        )
        if item is None:
            self.session.rollback()
            raise LookupError("daily_report_overview_item_not_found")
        return item

    def _latest_editorial_review(
        self, item_id: int
    ) -> DailyReportItemEditorialReviewRecord | None:
        return self.session.scalar(
            select(DailyReportItemEditorialReviewRecord)
            .where(DailyReportItemEditorialReviewRecord.daily_report_item_id == item_id)
            .order_by(
                DailyReportItemEditorialReviewRecord.revision.desc(),
                DailyReportItemEditorialReviewRecord.id.desc(),
            )
        )

    def _latest_overview_editorial_review(
        self, item_id: int
    ) -> DailyReportOverviewEditorialReviewRecord | None:
        return self.session.scalar(
            select(DailyReportOverviewEditorialReviewRecord)
            .where(
                DailyReportOverviewEditorialReviewRecord.daily_report_overview_item_id
                == item_id
            )
            .order_by(
                DailyReportOverviewEditorialReviewRecord.revision.desc(),
                DailyReportOverviewEditorialReviewRecord.id.desc(),
            )
        )

    def _matching_report(self, draft: DailyReportDraft) -> DailyReportRecord | None:
        if draft.supersedes_report_id is not None:
            return self.session.scalar(
                select(DailyReportRecord).where(
                    DailyReportRecord.supersedes_report_id == draft.supersedes_report_id
                )
            )
        return self.session.scalar(
            select(DailyReportRecord).where(
                DailyReportRecord.report_date == draft.report_date,
                DailyReportRecord.window_hours == draft.window_hours,
                DailyReportRecord.source_operation_id == draft.source_operation_id,
                DailyReportRecord.supersedes_report_id.is_(None),
            )
        )

    @staticmethod
    def _is_revision_conflict(error: IntegrityError) -> bool:
        original = error.orig
        diagnostics = getattr(original, "diag", None)
        constraint_name = getattr(diagnostics, "constraint_name", None)
        if constraint_name is not None:
            return constraint_name in {
                "uq_daily_report_identity",
                "uq_daily_report_revision",
                "uq_daily_report_supersedes",
            }

        sqlite_errorcode = getattr(original, "sqlite_errorcode", None)
        if sqlite_errorcode not in {1555, 2067}:
            return False
        message = str(original)
        return any(
            columns in message
            for columns in (
                "daily_reports.report_date, daily_reports.window_hours, "
                "daily_reports.source_operation_id",
                "daily_reports.report_date, daily_reports.window_hours, "
                "daily_reports.revision",
                "daily_reports.supersedes_report_id",
            )
        )
