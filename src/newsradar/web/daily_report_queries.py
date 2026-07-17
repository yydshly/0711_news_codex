from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from newsradar.daily_reports.intelligence import (
    DecisionReportItem,
    OverviewReportItem,
    build_decision_script,
    build_overview_script,
)
from newsradar.db.models import (
    DailyReportAudioArtifactRecord,
    DailyReportItemEditorialReviewRecord,
    DailyReportItemRecord,
    DailyReportOverviewEditorialReviewRecord,
    DailyReportOverviewItemRecord,
    DailyReportRecord,
    OperationRunRecord,
)
from newsradar.events.operation_snapshots import (
    event_snapshot_by_id,
    latest_complete_event_snapshot,
)
from newsradar.web.event_queries import EventQueryService


def _snapshot_string(snapshot: dict[str, object], key: str, fallback: str) -> str:
    value = snapshot.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _snapshot_float(snapshot: dict[str, object], key: str) -> float:
    value = snapshot.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


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
class DailyReportOverviewItemView:
    item_id: int | None
    event_id: int
    event_version_number: int
    position: int
    status: str
    display_tier: str
    rank_score: float
    zh_title: str
    zh_summary: str
    why_it_matters: str
    confirmation_summary: str
    detail_href: str
    snapshot: dict[str, object]
    editorial_review: DailyReportEditorialReviewView | None
    editorial_history: tuple[DailyReportEditorialReviewView, ...]
    duplicate_of_overview_item_id: int | None
    included_in_decision: bool


@dataclass(frozen=True, slots=True)
class DailyReportOverviewEditorialSummaryView:
    total_count: int
    included_count: int
    needs_evidence_count: int
    excluded_count: int
    duplicate_count: int
    unreviewed_count: int


@dataclass(frozen=True, slots=True)
class DailyReportOverviewView:
    items: tuple[DailyReportOverviewItemView, ...]
    confirmed: tuple[DailyReportOverviewItemView, ...]
    hotspots: tuple[DailyReportOverviewItemView, ...]
    signals: tuple[DailyReportOverviewItemView, ...]
    script: str
    summary: DailyReportOverviewEditorialSummaryView
    legacy_unreviewed: bool


@dataclass(frozen=True, slots=True)
class DailyReportAudioArtifactView:
    artifact_id: int
    rendition: str
    status: str
    error_code: str | None
    error_message: str | None
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class DailyReportAudioView:
    decision: DailyReportAudioArtifactView | None
    overview: DailyReportAudioArtifactView | None
    decision_operation_status: str | None
    overview_operation_status: str | None


@dataclass(frozen=True, slots=True)
class DailyReportEditorialSummaryView:
    total_count: int
    included_count: int
    needs_evidence_count: int
    excluded_count: int
    duplicate_count: int
    unreviewed_count: int


@dataclass(frozen=True, slots=True)
class DailyReportDetailView:
    report: DailyReportSummaryView
    generation_summary: dict[str, object]
    decision_script: str
    editorial_summary: DailyReportEditorialSummaryView
    overview: DailyReportOverviewView
    audio: DailyReportAudioView
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
            editorial_summary=DailyReportEditorialSummaryView(
                total_count=len(views),
                included_count=sum(row.included for row in views),
                needs_evidence_count=sum(
                    row.editorial_review is not None
                    and row.editorial_review.decision == "needs_evidence"
                    for row in views
                ),
                excluded_count=sum(
                    row.editorial_review is not None
                    and row.editorial_review.decision == "exclude"
                    for row in views
                ),
                duplicate_count=sum(
                    row.editorial_review is not None
                    and row.editorial_review.decision == "duplicate"
                    for row in views
                ),
                unreviewed_count=sum(row.editorial_review is None for row in views),
            ),
            overview=self._overview(record),
            audio=self._audio(record.id),
            supersedes_report_id=record.supersedes_report_id,
            archived_at=record.archived_at,
            confirmed=tuple(row for row in views if row.section == "confirmed"),
            emerging=tuple(row for row in views if row.section == "emerging"),
        )

    def _audio(self, report_id: int) -> DailyReportAudioView:
        records = self.session.scalars(
            select(DailyReportAudioArtifactRecord)
            .where(DailyReportAudioArtifactRecord.daily_report_id == report_id)
            .order_by(
                DailyReportAudioArtifactRecord.created_at.desc(),
                DailyReportAudioArtifactRecord.id.desc(),
            )
        )
        latest: dict[str, DailyReportAudioArtifactView] = {}
        for record in records:
            if record.rendition in latest:
                continue
            latest[record.rendition] = DailyReportAudioArtifactView(
                artifact_id=record.id,
                rendition=record.rendition,
                status=record.status,
                error_code=record.error_code,
                error_message=record.error_message,
                duration_ms=record.audio_duration_ms,
            )
        active: dict[str, str] = {}
        for record in self.session.scalars(
            select(OperationRunRecord)
            .where(
                OperationRunRecord.operation_type == "daily_report_audio",
                OperationRunRecord.status.in_(("queued", "running")),
            )
            .order_by(OperationRunRecord.id.desc())
        ):
            if not isinstance(record.requested_scope, dict):
                continue
            rendition = record.requested_scope.get("rendition")
            if (
                record.requested_scope.get("daily_report_id") != report_id
                or rendition not in {"decision", "overview"}
                or rendition in active
            ):
                continue
            active[rendition] = record.status
        return DailyReportAudioView(
            decision=latest.get("decision"),
            overview=latest.get("overview"),
            decision_operation_status=active.get("decision"),
            overview_operation_status=active.get("overview"),
        )

    def _overview(self, record: DailyReportRecord) -> DailyReportOverviewView:
        persisted = tuple(
            self.session.scalars(
                select(DailyReportOverviewItemRecord)
                .where(DailyReportOverviewItemRecord.daily_report_id == record.id)
                .order_by(
                    DailyReportOverviewItemRecord.position,
                    DailyReportOverviewItemRecord.id,
                )
            )
        )
        if persisted:
            histories: dict[int, list[DailyReportEditorialReviewView]] = {}
            duplicate_targets: dict[int, int | None] = {}
            for review in self.session.scalars(
                select(DailyReportOverviewEditorialReviewRecord)
                .where(
                    DailyReportOverviewEditorialReviewRecord.daily_report_overview_item_id.in_(
                        tuple(item.id for item in persisted)
                    )
                )
                .order_by(
                    DailyReportOverviewEditorialReviewRecord.daily_report_overview_item_id,
                    DailyReportOverviewEditorialReviewRecord.revision,
                    DailyReportOverviewEditorialReviewRecord.id,
                )
            ):
                view = DailyReportEditorialReviewView(
                    review_id=review.id,
                    revision=review.revision,
                    decision=review.decision,
                    zh_title=review.zh_title,
                    zh_summary=review.zh_summary,
                    review_recommendation=review.review_recommendation,
                    evidence_assessment=review.evidence_assessment,
                    created_at=review.created_at,
                )
                histories.setdefault(review.daily_report_overview_item_id, []).append(view)
                duplicate_targets[review.daily_report_overview_item_id] = (
                    review.duplicate_of_overview_item_id
                )
            items: list[DailyReportOverviewItemView] = []
            for row in persisted:
                snapshot = dict(row.snapshot) if isinstance(row.snapshot, dict) else {}
                history = tuple(histories.get(row.id, ()))
                latest = history[-1] if history else None
                items.append(
                    DailyReportOverviewItemView(
                        item_id=row.id,
                        event_id=row.event_id,
                        event_version_number=row.event_version_number,
                        position=row.position,
                        status=_snapshot_string(snapshot, "status", "emerging"),
                        display_tier=_snapshot_string(
                            snapshot, "display_tier", "audit_only"
                        ),
                        rank_score=_snapshot_float(snapshot, "rank_score"),
                        zh_title=(
                            latest.zh_title
                            if latest
                            else _snapshot_string(snapshot, "zh_title", "未命名事件")
                        ),
                        zh_summary=(
                            latest.zh_summary
                            if latest
                            else _snapshot_string(snapshot, "zh_summary", "暂无中文概述")
                        ),
                        why_it_matters=_snapshot_string(
                            snapshot, "why_it_matters", ""
                        ),
                        confirmation_summary=_snapshot_string(
                            snapshot, "confirmation_summary", ""
                        ),
                        detail_href=(
                            f"/events/{row.event_id}?operation_id="
                            f"{record.source_operation_id}&version={row.event_version_number}"
                        ),
                        snapshot=snapshot,
                        editorial_review=latest,
                        editorial_history=history,
                        duplicate_of_overview_item_id=(
                            duplicate_targets.get(row.id) if latest else None
                        ),
                        included_in_decision=row.decision_item_id is not None,
                    )
                )
            return self._overview_view(
                record.report_date,
                tuple(items),
                legacy_unreviewed=False,
            )

        snapshot = event_snapshot_by_id(
            self.session,
            record.source_operation_id,
            now=record.generated_at,
        )
        if snapshot is None:
            return self._overview_view(
                record.report_date, (), legacy_unreviewed=True
            )
        events = EventQueryService(self.session)
        version_by_event = {
            ref.event_id: ref.version_number for ref in snapshot.event_versions
        }
        items: list[DailyReportOverviewItemView] = []
        for position, event in enumerate(events._operation_rows(snapshot), start=1):
            if event.status != "confirmed" and event.display_tier not in {
                "hotspot",
                "signal",
            }:
                continue
            items.append(
                DailyReportOverviewItemView(
                    item_id=None,
                    event_id=event.event_id,
                    event_version_number=version_by_event[event.event_id],
                    position=position,
                    status=event.status,
                    display_tier=event.display_tier,
                    rank_score=event.rank_score,
                    zh_title=event.zh_title,
                    zh_summary=event.zh_summary,
                    why_it_matters=event.why_it_matters,
                    confirmation_summary=event.confirmation_summary,
                    detail_href=event.detail_href,
                    snapshot={
                        "zh_title": event.zh_title,
                        "zh_summary": event.zh_summary,
                        "why_it_matters": event.why_it_matters,
                        "status": event.status,
                        "display_tier": event.display_tier,
                        "rank_score": event.rank_score,
                        "confirmation_summary": event.confirmation_summary,
                        "evidence": [],
                        "limitations": [],
                    },
                    editorial_review=None,
                    editorial_history=(),
                    duplicate_of_overview_item_id=None,
                    included_in_decision=False,
                )
            )
        ordered = tuple(sorted(items, key=lambda item: (-item.rank_score, item.event_id)))
        return self._overview_view(
            record.report_date, ordered, legacy_unreviewed=True
        )

    @staticmethod
    def _overview_view(
        report_date: date,
        items: tuple[DailyReportOverviewItemView, ...],
        *,
        legacy_unreviewed: bool,
    ) -> DailyReportOverviewView:
        confirmed = tuple(item for item in items if item.status == "confirmed")
        hotspots = tuple(
            item
            for item in items
            if item.status != "confirmed" and item.display_tier == "hotspot"
        )
        signals = tuple(
            item
            for item in items
            if item.status != "confirmed" and item.display_tier == "signal"
        )
        return DailyReportOverviewView(
            items=items,
            confirmed=confirmed,
            hotspots=hotspots,
            signals=signals,
            script=build_overview_script(
                report_date=report_date,
                items=(
                    OverviewReportItem(
                        event_id=item.event_id,
                        status=item.status,
                        display_tier=item.display_tier,
                        rank_score=item.rank_score,
                        zh_title=item.zh_title,
                        zh_summary=item.zh_summary,
                        why_it_matters=item.why_it_matters,
                        confirmation_summary=item.confirmation_summary,
                        decision=(
                            item.editorial_review.decision
                            if item.editorial_review
                            else None
                        ),
                        recommendation=(
                            item.editorial_review.review_recommendation
                            if item.editorial_review
                            else None
                        ),
                        evidence_assessment=(
                            item.editorial_review.evidence_assessment
                            if item.editorial_review
                            else None
                        ),
                    )
                    for item in items
                ),
            ),
            summary=DailyReportOverviewEditorialSummaryView(
                total_count=len(items),
                included_count=sum(
                    item.editorial_review is not None
                    and item.editorial_review.decision in {"keep", "needs_evidence"}
                    for item in items
                ),
                needs_evidence_count=sum(
                    item.editorial_review is not None
                    and item.editorial_review.decision == "needs_evidence"
                    for item in items
                ),
                excluded_count=sum(
                    item.editorial_review is not None
                    and item.editorial_review.decision == "exclude"
                    for item in items
                ),
                duplicate_count=sum(
                    item.editorial_review is not None
                    and item.editorial_review.decision == "duplicate"
                    for item in items
                ),
                unreviewed_count=sum(item.editorial_review is None for item in items),
            ),
            legacy_unreviewed=legacy_unreviewed,
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
