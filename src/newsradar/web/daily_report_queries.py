from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from newsradar.daily_reports.intelligence import (
    DecisionReportItem,
    build_decision_script,
)
from newsradar.db.models import (
    DailyReportItemEditorialReviewRecord,
    DailyReportItemRecord,
    DailyReportRecord,
)
from newsradar.events.operation_snapshots import latest_complete_event_snapshot


@dataclass(frozen=True, slots=True)
class DailyReportSummaryView:
    report_id: int
    report_date: date
    revision: int
    status: str
    window_hours: int
    window_end: datetime
    source_operation_id: int
    confirmed_count: int
    emerging_count: int


@dataclass(frozen=True, slots=True)
class DailyReportEditorialReviewView:
    review_id: int
    revision: int
    decision: str
    zh_title: str
    zh_summary: str
    review_recommendation: str
    evidence_assessment: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DailyReportItemView:
    item_id: int
    event_id: int
    event_version_number: int
    section: str
    position: int
    included: bool
    snapshot: dict[str, object]
    editorial_review: DailyReportEditorialReviewView | None
    editorial_history: tuple[DailyReportEditorialReviewView, ...]


@dataclass(frozen=True, slots=True)
class DailyReportDetailView:
    report: DailyReportSummaryView
    generation_summary: dict[str, object]
    decision_script: str
    supersedes_report_id: int | None
    archived_at: datetime | None
    confirmed: tuple[DailyReportItemView, ...]
    emerging: tuple[DailyReportItemView, ...]


class DailyReportQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_reports(self, *, limit: int = 100) -> tuple[DailyReportSummaryView, ...]:
        records = self.session.scalars(
            select(DailyReportRecord)
            .order_by(
                DailyReportRecord.report_date.desc(),
                DailyReportRecord.revision.desc(),
                DailyReportRecord.id.desc(),
            )
            .limit(max(1, min(limit, 100)))
        )
        return tuple(self._summary(record) for record in records)

    def detail(self, report_id: int) -> DailyReportDetailView | None:
        record = self.session.get(DailyReportRecord, report_id)
        if record is None:
            return None
        rows = tuple(
            self.session.scalars(
                select(DailyReportItemRecord)
                .where(DailyReportItemRecord.daily_report_id == report_id)
                .order_by(
                    case((DailyReportItemRecord.section == "confirmed", 0), else_=1),
                    DailyReportItemRecord.position,
                    DailyReportItemRecord.id,
                )
            )
        )
        review_history_by_item: dict[
            int, tuple[DailyReportEditorialReviewView, ...]
        ] = {}
        if rows:
            review_views_by_item: dict[int, list[DailyReportEditorialReviewView]] = {}
            reviews = self.session.scalars(
                select(DailyReportItemEditorialReviewRecord)
                .where(
                    DailyReportItemEditorialReviewRecord.daily_report_item_id.in_(
                        tuple(row.id for row in rows)
                    )
                )
                .order_by(
                    DailyReportItemEditorialReviewRecord.daily_report_item_id,
                    DailyReportItemEditorialReviewRecord.revision,
                    DailyReportItemEditorialReviewRecord.id,
                )
            )
            for review in reviews:
                review_views_by_item.setdefault(
                    review.daily_report_item_id, []
                ).append(
                    DailyReportEditorialReviewView(
                        review_id=review.id,
                        revision=review.revision,
                        decision=review.decision,
                        zh_title=review.zh_title,
                        zh_summary=review.zh_summary,
                        review_recommendation=review.review_recommendation,
                        evidence_assessment=review.evidence_assessment,
                        created_at=review.created_at,
                    )
                )
            review_history_by_item = {
                item_id: tuple(history)
                for item_id, history in review_views_by_item.items()
            }
        views = tuple(
            DailyReportItemView(
                item_id=row.id,
                event_id=row.event_id,
                event_version_number=row.event_version_number,
                section=row.section,
                position=row.position,
                included=row.included,
                snapshot=dict(row.snapshot) if isinstance(row.snapshot, dict) else {},
                editorial_review=(
                    review_history_by_item[row.id][-1]
                    if row.id in review_history_by_item
                    else None
                ),
                editorial_history=review_history_by_item.get(row.id, ()),
            )
            for row in rows
        )
        decision_script = build_decision_script(
            report_date=record.report_date,
            items=(
                DecisionReportItem(
                    included=row.included,
                    section=row.section,
                    position=row.position,
                    snapshot=row.snapshot,
                    decision=(row.editorial_review.decision if row.editorial_review else None),
                    zh_title=(row.editorial_review.zh_title if row.editorial_review else None),
                    zh_summary=(
                        row.editorial_review.zh_summary if row.editorial_review else None
                    ),
                    recommendation=(
                        row.editorial_review.review_recommendation
                        if row.editorial_review
                        else None
                    ),
                    evidence_assessment=(
                        row.editorial_review.evidence_assessment
                        if row.editorial_review
                        else None
                    ),
                )
                for row in views
            ),
        )
        return DailyReportDetailView(
            report=self._summary(record, rows=rows),
            generation_summary=(
                dict(record.generation_summary)
                if isinstance(record.generation_summary, dict)
                else {}
            ),
            decision_script=decision_script,
            supersedes_report_id=record.supersedes_report_id,
            archived_at=record.archived_at,
            confirmed=tuple(row for row in views if row.section == "confirmed"),
            emerging=tuple(row for row in views if row.section == "emerging"),
        )

    def has_complete_event_snapshot(self, *, now: datetime | None = None) -> bool:
        return latest_complete_event_snapshot(self.session, now=now) is not None

    def _summary(
        self,
        record: DailyReportRecord,
        *,
        rows: tuple[DailyReportItemRecord, ...] | None = None,
    ) -> DailyReportSummaryView:
        loaded = rows
        if loaded is None:
            loaded = tuple(
                self.session.scalars(
                    select(DailyReportItemRecord).where(
                        DailyReportItemRecord.daily_report_id == record.id,
                        DailyReportItemRecord.included.is_(True),
                    )
                )
            )
        return DailyReportSummaryView(
            report_id=record.id,
            report_date=record.report_date,
            revision=record.revision,
            status=record.status,
            window_hours=record.window_hours,
            window_end=record.window_end,
            source_operation_id=record.source_operation_id,
            confirmed_count=sum(
                row.included and row.section == "confirmed" for row in loaded
            ),
            emerging_count=sum(
                row.included and row.section == "emerging" for row in loaded
            ),
        )
