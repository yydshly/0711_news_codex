from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from newsradar.daily_reports.chinese_enrichment import (
    DAILY_CHINESE_ERROR_LABELS,
    DAILY_CHINESE_FIELD_ERROR_CODES,
    DAILY_CHINESE_SAFE_ERROR_CODES,
    candidate_key,
)
from newsradar.daily_reports.intelligence import (
    DecisionReportItem,
    OverviewReportItem,
    build_decision_script,
    build_overview_script,
)
from newsradar.daily_reports.retention import report_local_date
from newsradar.daily_reports.text_integrity import has_suspicious_question_run
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
from newsradar.settings import MAX_DAILY_REPORT_MODEL_ITEMS
from newsradar.web.event_queries import EventQueryService


def _snapshot_string(snapshot: dict[str, object], key: str, fallback: str) -> str:
    value = snapshot.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _snapshot_float(snapshot: dict[str, object], key: str) -> float:
    value = snapshot.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


_EVENT_VERSION_KEY = re.compile(r"[1-9]\d*:[1-9]\d*")


def _non_negative_integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _is_non_negative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _generation_count(
    generation_summary: dict[str, object], key: str, fallback: int
) -> int:
    value = generation_summary.get(key)
    return value if _is_non_negative_integer(value) else fallback


@dataclass(frozen=True, slots=True)
class DailyReportChineseOriginView:
    origin: str
    error_code: str | None
    label_zh: str


_DAILY_MODEL_ENRICHMENT_REASON = (
    "本条中文标题和概述已完成日报增强；确认状态、证据与收录范围仍以固定快照为准。"
)
_STALE_RULE_FALLBACK_REASON = "已按可追溯规则汇总；中文增强暂不可用。"
_STALE_MODEL_UNAVAILABLE_LIMITATION = "中文模型不可用，当前使用规则回退"


def _display_snapshot(
    snapshot: dict[str, object],
    chinese_origin: DailyReportChineseOriginView | None,
) -> dict[str, object]:
    display = dict(snapshot)
    if chinese_origin is None or chinese_origin.origin not in {"model", "model_partial"}:
        return display
    if display.get("why_it_matters") == _STALE_RULE_FALLBACK_REASON:
        display["why_it_matters"] = _DAILY_MODEL_ENRICHMENT_REASON
    limitations = display.get("limitations")
    if isinstance(limitations, list):
        display["limitations"] = [
            limitation
            for limitation in limitations
            if limitation != _STALE_MODEL_UNAVAILABLE_LIMITATION
        ]
    elif isinstance(limitations, tuple):
        display["limitations"] = tuple(
            limitation
            for limitation in limitations
            if limitation != _STALE_MODEL_UNAVAILABLE_LIMITATION
        )
    return display


@dataclass(frozen=True, slots=True)
class DailyReportChineseEnrichmentView:
    candidate_total: int
    processed: int
    model_success: int
    partial_fallback: int
    rule_fallback: int
    budget_fallback: int
    error_counts: dict[str, int]
    error_labels: dict[str, str]
    recorded: bool


def _chinese_enrichment_view(
    generation_summary: dict[str, object],
) -> tuple[DailyReportChineseEnrichmentView, dict[str, DailyReportChineseOriginView]]:
    raw = generation_summary.get("daily_chinese_enrichment")
    count_keys = (
        "candidate_total",
        "processed",
        "model_success",
        "rule_fallback",
        "budget_fallback",
    )
    if (
        not isinstance(raw, dict)
        or not all(_is_non_negative_integer(raw.get(key)) for key in count_keys)
        or not isinstance(raw.get("error_counts"), dict)
        or not isinstance(raw.get("items"), dict)
    ):
        return _empty_chinese_enrichment_view()
    candidate_total = raw["candidate_total"]
    processed = raw["processed"]
    model_success = raw["model_success"]
    partial_fallback = raw.get("partial_fallback", 0)
    rule_fallback = raw["rule_fallback"]
    budget_fallback = raw["budget_fallback"]
    if (
        not _is_non_negative_integer(partial_fallback)
        or processed > candidate_total
        or model_success + partial_fallback + rule_fallback + budget_fallback
        != processed
    ):
        return _empty_chinese_enrichment_view()
    model_budget = raw.get("model_budget")
    if model_budget is not None:
        if (
            not _is_non_negative_integer(model_budget)
            or model_budget > MAX_DAILY_REPORT_MODEL_ITEMS
        ):
            return _empty_chinese_enrichment_view()
        if (
            model_success + partial_fallback + rule_fallback
            > min(candidate_total, model_budget)
            or budget_fallback > max(candidate_total - model_budget, 0)
        ):
            return _empty_chinese_enrichment_view()

    raw_errors = raw["error_counts"]
    if not all(
        isinstance(key, str)
        and key in DAILY_CHINESE_SAFE_ERROR_CODES
        and _is_non_negative_integer(value)
        and value > 0
        for key, value in raw_errors.items()
    ):
        return _empty_chinese_enrichment_view()
    origins: dict[str, DailyReportChineseOriginView] = {}
    derived_origins: Counter[str] = Counter()
    derived_errors: Counter[str] = Counter()
    raw_items = raw["items"]
    for key, value in raw_items.items():
        if (
            not isinstance(key, str)
            or _EVENT_VERSION_KEY.fullmatch(key) is None
            or not isinstance(value, dict)
        ):
            return _empty_chinese_enrichment_view()
        origin = value.get("origin")
        error = value.get("error_code")
        if origin == "model" and error is None:
            origins[key] = DailyReportChineseOriginView("model", None, "MiniMax")
            field_errors: tuple[str, ...] = ()
        elif origin == "model_partial" and isinstance(error, str):
            raw_field_errors = value.get("field_errors")
            if not isinstance(raw_field_errors, list) or not raw_field_errors:
                return _empty_chinese_enrichment_view()
            field_errors = tuple(raw_field_errors)
            if (
                len(field_errors) > 4
                or not all(isinstance(code, str) for code in field_errors)
                or len(set(field_errors)) != len(field_errors)
                or any(code not in DAILY_CHINESE_FIELD_ERROR_CODES for code in field_errors)
                or error != field_errors[0]
            ):
                return _empty_chinese_enrichment_view()
            labels = "、".join(DAILY_CHINESE_ERROR_LABELS[code] for code in field_errors)
            origins[key] = DailyReportChineseOriginView(
                "model_partial", error, f"MiniMax 部分成功（{labels}）"
            )
        elif (
            origin == "rule_fallback"
            and isinstance(error, str)
            and error in DAILY_CHINESE_SAFE_ERROR_CODES
            and error != "budget_limit"
        ):
            label = DAILY_CHINESE_ERROR_LABELS[error]
            origins[key] = DailyReportChineseOriginView(
                "rule_fallback", error, f"规则回退（{label}）"
            )
            raw_field_errors = value.get("field_errors")
            field_errors = (
                tuple(raw_field_errors)
                if isinstance(raw_field_errors, list)
                and all(
                    isinstance(code, str) and code in DAILY_CHINESE_FIELD_ERROR_CODES
                    for code in raw_field_errors
                )
                else ()
            )
        elif origin == "budget_limit" and error == "budget_limit":
            origins[key] = DailyReportChineseOriginView(
                "budget_limit", "budget_limit", "安全上限回退（本期安全上限）"
            )
            field_errors = ()
        else:
            return _empty_chinese_enrichment_view()
        derived_origins[origin] += 1
        if field_errors:
            derived_errors.update(field_errors)
        elif isinstance(error, str):
            derived_errors[error] += 1
    errors = dict(sorted(derived_errors.items()))
    if (
        len(raw_items) != processed
        or derived_origins["model"] != model_success
        or derived_origins["model_partial"] != partial_fallback
        or derived_origins["rule_fallback"] != rule_fallback
        or derived_origins["budget_limit"] != budget_fallback
        or dict(sorted(raw_errors.items())) != errors
    ):
        return _empty_chinese_enrichment_view()
    return (
        DailyReportChineseEnrichmentView(
            candidate_total=candidate_total,
            processed=processed,
            model_success=model_success,
            partial_fallback=partial_fallback,
            rule_fallback=rule_fallback,
            budget_fallback=budget_fallback,
            error_counts=errors,
            error_labels={code: DAILY_CHINESE_ERROR_LABELS[code] for code in errors},
            recorded=True,
        ),
        origins,
    )


def _empty_chinese_enrichment_view() -> tuple[
    DailyReportChineseEnrichmentView, dict[str, DailyReportChineseOriginView]
]:
    return DailyReportChineseEnrichmentView(0, 0, 0, 0, 0, 0, {}, {}, False), {}


@dataclass(frozen=True, slots=True)
class DailyReportSummaryView:
    report_id: int
    report_date: date
    revision: int
    status: str
    window_hours: int
    window_end: datetime
    source_operation_id: int
    pinned_at: datetime | None
    confirmed_count: int
    emerging_count: int


@dataclass(frozen=True, slots=True)
class DailyReportTrashStateView:
    report_id: int
    deleted_at: datetime
    purge_after: datetime | None


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
    text_integrity_error: bool


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
    chinese_origin: DailyReportChineseOriginView | None


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
    chinese_origin: DailyReportChineseOriginView | None


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
    included: tuple[DailyReportOverviewItemView, ...]
    included_confirmed: tuple[DailyReportOverviewItemView, ...]
    included_hotspots: tuple[DailyReportOverviewItemView, ...]
    included_signals: tuple[DailyReportOverviewItemView, ...]
    script: str
    summary: DailyReportOverviewEditorialSummaryView
    legacy_unreviewed: bool


def _normalize_included_overview_item(
    item: DailyReportOverviewItemView,
) -> DailyReportOverviewItemView:
    if item.status == "confirmed" or item.display_tier in {"hotspot", "signal"}:
        return item
    return replace(
        item,
        display_tier="signal",
        snapshot={
            **item.snapshot,
            "overview_display_diagnostic_zh": (
                "全览展示层级缺失或不兼容，已降级为新兴信号。"
            ),
        },
    )


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
class DailyReportTextIntegrityView:
    corrupted_review_count: int


@dataclass(frozen=True, slots=True)
class DailyReportCoverageView:
    cumulative_event_count: int
    decision_count: int
    overview_count: int
    omitted_from_decision_count: int


@dataclass(frozen=True, slots=True)
class DailyReportDetailView:
    report: DailyReportSummaryView
    generation_summary: dict[str, object]
    coverage: DailyReportCoverageView
    chinese_enrichment: DailyReportChineseEnrichmentView
    decision_script: str
    editorial_summary: DailyReportEditorialSummaryView
    text_integrity: DailyReportTextIntegrityView
    overview: DailyReportOverviewView
    audio: DailyReportAudioView
    supersedes_report_id: int | None
    archived_at: datetime | None
    confirmed: tuple[DailyReportItemView, ...]
    emerging: tuple[DailyReportItemView, ...]


class DailyReportQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_reports(
        self,
        *,
        limit: int = 100,
        period: str = "all",
        now: datetime | None = None,
    ) -> tuple[DailyReportSummaryView, ...]:
        statement = select(DailyReportRecord).where(DailyReportRecord.deleted_at.is_(None))
        if period in {"7", "30"}:
            current = now or datetime.now(UTC)
            statement = statement.where(
                DailyReportRecord.report_date
                >= report_local_date(current) - timedelta(days=int(period) - 1)
            )
        elif period == "pinned":
            statement = statement.where(DailyReportRecord.pinned_at.is_not(None))
        elif period != "all":
            raise ValueError("invalid_daily_report_period")
        records = self.session.scalars(
            statement
            .order_by(
                DailyReportRecord.report_date.desc(),
                DailyReportRecord.revision.desc(),
                DailyReportRecord.id.desc(),
            )
            .limit(max(1, min(limit, 100)))
        )
        return tuple(self._summary(record) for record in records)

    def trash_reports(
        self, *, page: int, page_size: int
    ) -> tuple[DailyReportSummaryView, ...]:
        safe_page = max(1, page)
        safe_page_size = max(1, min(page_size, 100))
        records = self.session.scalars(
            select(DailyReportRecord)
            .where(DailyReportRecord.deleted_at.is_not(None))
            .order_by(
                DailyReportRecord.purge_after.asc(),
                DailyReportRecord.id.asc(),
            )
            .offset((safe_page - 1) * safe_page_size)
            .limit(safe_page_size)
        )
        return tuple(self._summary(record) for record in records)

    def trash_state(self, report_id: int) -> DailyReportTrashStateView | None:
        record = self.session.scalar(
            select(DailyReportRecord).where(
                DailyReportRecord.id == report_id,
                DailyReportRecord.deleted_at.is_not(None),
            )
        )
        if record is None or record.deleted_at is None:
            return None
        return DailyReportTrashStateView(
            report_id=record.id,
            deleted_at=record.deleted_at,
            purge_after=record.purge_after,
        )

    def detail(self, report_id: int) -> DailyReportDetailView | None:
        record = self.session.scalar(
            select(DailyReportRecord).where(
                DailyReportRecord.id == report_id,
                DailyReportRecord.deleted_at.is_(None),
            )
        )
        if record is None:
            return None
        generation_summary = (
            dict(record.generation_summary)
            if isinstance(record.generation_summary, dict)
            else {}
        )
        chinese_enrichment, chinese_origins = _chinese_enrichment_view(
            generation_summary
        )
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
                        text_integrity_error=self._has_suspicious_text(
                            review.zh_title,
                            review.zh_summary,
                            review.review_recommendation,
                            review.evidence_assessment,
                        ),
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
                snapshot=_display_snapshot(
                    dict(row.snapshot) if isinstance(row.snapshot, dict) else {},
                    chinese_origin,
                ),
                editorial_review=(
                    review_history_by_item[row.id][-1]
                    if row.id in review_history_by_item
                    else None
                ),
                editorial_history=review_history_by_item.get(row.id, ()),
                chinese_origin=chinese_origin,
            )
            for row in rows
            for chinese_origin in (
                chinese_origins.get(
                    candidate_key(row.event_id, row.event_version_number)
                ),
            )
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
        overview = self._overview(record, chinese_origins)
        coverage = self._coverage(generation_summary, rows, overview.items)
        return DailyReportDetailView(
            report=self._summary(record, rows=rows),
            generation_summary=generation_summary,
            coverage=coverage,
            chinese_enrichment=chinese_enrichment,
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
            text_integrity=DailyReportTextIntegrityView(
                corrupted_review_count=sum(
                    self._review_has_suspicious_text(item.editorial_review)
                    for item in (*views, *overview.items)
                )
            ),
            overview=overview,
            audio=self._audio(record.id),
            supersedes_report_id=record.supersedes_report_id,
            archived_at=record.archived_at,
            confirmed=tuple(row for row in views if row.section == "confirmed"),
            emerging=tuple(row for row in views if row.section == "emerging"),
        )

    @staticmethod
    def _coverage(
        generation_summary: dict[str, object],
        decision_rows: tuple[DailyReportItemRecord, ...],
        overview_rows: tuple[DailyReportOverviewItemView, ...],
    ) -> DailyReportCoverageView:
        if overview_rows:
            overview_count = len(overview_rows)
            decision_count = len(decision_rows)
            return DailyReportCoverageView(
                cumulative_event_count=overview_count,
                decision_count=decision_count,
                overview_count=overview_count,
                omitted_from_decision_count=max(overview_count - decision_count, 0),
            )
        overview_count = _generation_count(
            generation_summary, "overview_count", len(overview_rows)
        )
        decision_count = _generation_count(
            generation_summary, "decision_count", len(decision_rows)
        )
        omitted_from_decision_count = _generation_count(
            generation_summary,
            "omitted_from_decision_count",
            max(overview_count - decision_count, 0),
        )
        return DailyReportCoverageView(
            cumulative_event_count=overview_count,
            decision_count=decision_count,
            overview_count=overview_count,
            omitted_from_decision_count=omitted_from_decision_count,
        )

    @staticmethod
    def _review_has_suspicious_text(
        review: DailyReportEditorialReviewView | None,
    ) -> bool:
        return review is not None and review.text_integrity_error

    @staticmethod
    def _has_suspicious_text(*values: str) -> bool:
        return any(has_suspicious_question_run(value) for value in values)

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

    def _overview(
        self,
        record: DailyReportRecord,
        chinese_origins: dict[str, DailyReportChineseOriginView],
    ) -> DailyReportOverviewView:
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
                    text_integrity_error=self._has_suspicious_text(
                        review.zh_title,
                        review.zh_summary,
                        review.review_recommendation,
                        review.evidence_assessment,
                    ),
                )
                histories.setdefault(review.daily_report_overview_item_id, []).append(view)
                duplicate_targets[review.daily_report_overview_item_id] = (
                    review.duplicate_of_overview_item_id
                )
            items: list[DailyReportOverviewItemView] = []
            for row in persisted:
                snapshot = dict(row.snapshot) if isinstance(row.snapshot, dict) else {}
                chinese_origin = chinese_origins.get(
                    candidate_key(row.event_id, row.event_version_number)
                )
                snapshot = _display_snapshot(snapshot, chinese_origin)
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
                        chinese_origin=chinese_origin,
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
            chinese_origin = chinese_origins.get(
                candidate_key(event.event_id, version_by_event[event.event_id])
            )
            item_snapshot = _display_snapshot(
                {
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
                chinese_origin,
            )
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
                    why_it_matters=_snapshot_string(item_snapshot, "why_it_matters", ""),
                    confirmation_summary=_snapshot_string(
                        item_snapshot, "confirmation_summary", ""
                    ),
                    detail_href=event.detail_href,
                    snapshot=item_snapshot,
                    editorial_review=None,
                    editorial_history=(),
                    duplicate_of_overview_item_id=None,
                    included_in_decision=False,
                    chinese_origin=chinese_origin,
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
        included = tuple(
            _normalize_included_overview_item(item)
            for item in items
            if item.editorial_review is not None
            and item.editorial_review.decision in {"keep", "needs_evidence"}
        )
        return DailyReportOverviewView(
            items=items,
            confirmed=confirmed,
            hotspots=hotspots,
            signals=signals,
            included=included,
            included_confirmed=tuple(
                item for item in included if item.status == "confirmed"
            ),
            included_hotspots=tuple(
                item
                for item in included
                if item.status != "confirmed" and item.display_tier == "hotspot"
            ),
            included_signals=tuple(
                item
                for item in included
                if item.status != "confirmed" and item.display_tier == "signal"
            ),
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
                    for item in included
                ),
            ),
            summary=DailyReportOverviewEditorialSummaryView(
                total_count=len(items),
                included_count=len(included),
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
            pinned_at=record.pinned_at,
            confirmed_count=sum(
                row.included and row.section == "confirmed" for row in loaded
            ),
            emerging_count=sum(
                row.included and row.section == "emerging" for row in loaded
            ),
        )
