from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import case, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newsradar.ai.minimax import bounded_token_count
from newsradar.daily_reports.chinese_enrichment import (
    DAILY_CHINESE_FIELD_ERROR_CODES,
    DAILY_CHINESE_SAFE_ERROR_CODES,
    DailyReportChineseCandidate,
    DailyReportChineseResult,
    candidate_key,
)
from newsradar.daily_reports.retention import (
    RETENTION_DAYS,
    TRASH_BATCH_LIMIT,
    TRASH_DAYS,
    RetentionActionResult,
    report_local_date,
)
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
from newsradar.daily_reports.text_integrity import ensure_editorial_text_integrity
from newsradar.db.models import (
    DailyAutopilotRunRecord,
    DailyReportAudioArtifactRecord,
    DailyReportItemEditorialReviewRecord,
    DailyReportItemRecord,
    DailyReportOverviewEditorialReviewRecord,
    DailyReportOverviewItemRecord,
    DailyReportRecord,
    ModelUsageRecord,
    OperationRunRecord,
)

MAX_REVISION_ATTEMPTS = 3
_DAILY_CHINESE_ENRICHMENT_PURPOSE = "daily_report_chinese_enrichment"
_SAFE_DAILY_CHINESE_ORIGINS = frozenset(
    {"model", "model_partial", "rule_fallback", "budget_limit"}
)
_SAFE_DAILY_CHINESE_OUTCOMES = frozenset({"success", "fallback", "retry"})
_SAFE_MODEL_NAME = re.compile(r"[A-Za-z0-9._-]{1,120}")
_MAX_MODEL_LATENCY_MS = 300_000.0


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

    def pin(self, report_id: int) -> RetentionActionResult:
        report = self._report_for_update(report_id)
        if report.pinned_at is not None:
            self.session.commit()
            return RetentionActionResult(report_id, "unchanged", "日报已经置顶。")
        report.pinned_at = self._utcnow()
        self.session.commit()
        return RetentionActionResult(report_id, "pinned", "日报已置顶。")

    def unpin(self, report_id: int) -> RetentionActionResult:
        report = self._report_for_update(report_id)
        if report.pinned_at is None:
            self.session.commit()
            return RetentionActionResult(report_id, "unchanged", "日报未置顶。")
        report.pinned_at = None
        self.session.commit()
        return RetentionActionResult(report_id, "unpinned", "日报已取消置顶。")

    def move_to_trash(
        self, report_id: int, *, automatic: bool = False
    ) -> RetentionActionResult:
        report = self._report_for_update(report_id)
        if report.deleted_at is not None:
            self.session.commit()
            return RetentionActionResult(report_id, "unchanged", "日报已在回收站中。")
        if automatic and report.pinned_at is not None:
            self.session.commit()
            return RetentionActionResult(
                report_id, "unchanged", "日报已置顶，自动清理已跳过。"
            )
        blocked = self._trash_block_diagnostic(report_id)
        if blocked is not None:
            self.session.commit()
            return RetentionActionResult(report_id, "blocked", blocked)
        deleted_at = self._utcnow()
        report.deleted_at = deleted_at
        report.purge_after = deleted_at + timedelta(days=TRASH_DAYS)
        self.session.commit()
        return RetentionActionResult(report_id, "trashed", "日报已移入回收站。")

    def restore(self, report_id: int) -> RetentionActionResult:
        report = self._report_for_update(report_id)
        if report.deleted_at is None:
            self.session.commit()
            return RetentionActionResult(report_id, "unchanged", "日报不在回收站中。")
        report.deleted_at = None
        report.purge_after = None
        self.session.commit()
        return RetentionActionResult(report_id, "restored", "日报已从回收站恢复。")

    def trash_candidates(self) -> tuple[DailyReportRecord, ...]:
        retention_start = report_local_date(self._utcnow()) - timedelta(
            days=RETENTION_DAYS
        )
        return tuple(
            self.session.scalars(
                select(DailyReportRecord)
                .where(
                    DailyReportRecord.deleted_at.is_(None),
                    DailyReportRecord.pinned_at.is_(None),
                    DailyReportRecord.report_date <= retention_start,
                )
                .order_by(DailyReportRecord.report_date, DailyReportRecord.id)
                .limit(TRASH_BATCH_LIMIT)
            )
        )

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

    def chinese_enrichment_candidates(
        self, report_id: int
    ) -> tuple[DailyReportChineseCandidate, ...]:
        rows: dict[str, DailyReportChineseCandidate] = {}
        for item in self.items(report_id):
            row = DailyReportChineseCandidate(
                event_id=item.event_id,
                event_version_number=item.event_version_number,
                snapshot=dict(item.snapshot),
                decision_item_id=item.id,
                overview_item_id=None,
            )
            rows[row.key] = row
        for item in self.overview_items(report_id):
            key = candidate_key(item.event_id, item.event_version_number)
            existing = rows.get(key)
            rows[key] = (
                replace(existing, overview_item_id=item.id)
                if existing is not None
                else DailyReportChineseCandidate(
                    event_id=item.event_id,
                    event_version_number=item.event_version_number,
                    snapshot=dict(item.snapshot),
                    decision_item_id=None,
                    overview_item_id=item.id,
                )
            )
        return tuple(rows.values())

    def completed_chinese_enrichment_keys(self, report_id: int) -> frozenset[str]:
        report = self._draft_report(report_id)
        summary = (
            report.generation_summary
            if isinstance(report.generation_summary, dict)
            else {}
        )
        audit = summary.get("daily_chinese_enrichment")
        items = audit.get("items") if isinstance(audit, dict) else None
        candidates = {row.key: row for row in self.chinese_enrichment_candidates(report_id)}
        if not isinstance(items, dict):
            return frozenset()
        return frozenset(
            key
            for key in items
            if isinstance(key, str)
            and key in candidates
            and self._automatic_reviews_complete(candidates[key])
        )

    def save_overview_editorial_review(
        self,
        report_id: int,
        item_id: int,
        draft: DailyReportOverviewEditorialReviewDraft,
        *,
        commit: bool = True,
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
        if commit:
            self.session.commit()
        else:
            self.session.flush()
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

    def assert_audio_package_ready(self, report_id: int) -> None:
        """Validate both report renditions without archiving or committing."""
        report = self.session.get(DailyReportRecord, report_id)
        if report is None:
            raise LookupError("daily_report_not_found")
        if report.status != ReportStatus.DRAFT.value:
            raise ValueError("daily_report_archived")
        decision_items = self.items(report_id)
        overview_items = self.overview_items(report_id)
        if not decision_items:
            raise ValueError("daily_report_decision_has_no_items")
        if not overview_items:
            raise ValueError("daily_report_overview_has_no_items")
        decision_reviews = tuple(
            self._latest_editorial_review(item.id) for item in decision_items
        )
        if any(review is None for review in decision_reviews):
            raise ValueError("daily_report_decision_review_incomplete")
        included_decisions = {
            EditorialDecision.KEEP.value,
            EditorialDecision.NEEDS_EVIDENCE.value,
        }
        if not any(
            review is not None and review.decision in included_decisions
            for review in decision_reviews
        ):
            raise ValueError("daily_report_decision_has_no_included_items")
        overview = self.overview_audio_readiness(report_id)
        if overview.reviewed_count != overview.total_count:
            raise ValueError("daily_report_overview_review_incomplete")
        if overview.included_count == 0:
            raise ValueError("daily_report_overview_has_no_included_items")
        self.assert_text_integrity(report_id)

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
        *,
        commit: bool = True,
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
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return review

    def save_automatic_chinese_reviews(
        self,
        report_id: int,
        result: DailyReportChineseResult,
        decision_draft: DailyReportEditorialReviewDraft | None,
        overview_draft: DailyReportOverviewEditorialReviewDraft | None,
        *,
        candidate_total: int,
        model_budget: int,
    ) -> bool:
        report = self._draft_report(report_id)
        summary = dict(report.generation_summary)
        audit = dict(summary.get("daily_chinese_enrichment") or {})
        item_audits = dict(audit.get("items") or {})
        if (
            result.candidate.key in item_audits
            and self._automatic_reviews_complete(result.candidate)
        ):
            return False

        usage_ids: list[int] = []
        for usage in result.usages:
            record = ModelUsageRecord(
                purpose=_DAILY_CHINESE_ENRICHMENT_PURPOSE,
                model=_safe_model_name(usage.model),
                input_tokens=bounded_token_count(usage.input_tokens),
                output_tokens=bounded_token_count(usage.output_tokens),
                latency_ms=_bounded_latency_ms(usage.latency_ms),
                outcome=_safe_usage_outcome(usage.outcome),
                error=_safe_error_code(usage.error),
            )
            self.session.add(record)
            self.session.flush()
            usage_ids.append(record.id)

        if decision_draft is not None and result.candidate.decision_item_id is not None:
            self.save_editorial_review(
                report_id,
                result.candidate.decision_item_id,
                decision_draft,
                commit=False,
            )
        if overview_draft is not None and result.candidate.overview_item_id is not None:
            self.save_overview_editorial_review(
                report_id,
                result.candidate.overview_item_id,
                overview_draft,
                commit=False,
            )

        item_audits[result.candidate.key] = {
            "origin": _safe_origin(result.origin),
            "error_code": _safe_error_code(result.error_code),
            "field_errors": list(_safe_field_errors(result.field_errors)),
            "model": _safe_model_name(result.model),
            "model_usage_ids": usage_ids,
        }
        summary["daily_chinese_enrichment"] = rebuild_chinese_enrichment_summary(
            item_audits,
            candidate_total=candidate_total,
            model_budget=model_budget,
        )
        report.generation_summary = summary
        self.session.commit()
        return True

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
        self.assert_text_integrity(report.id)
        report.status = ReportStatus.ARCHIVED.value
        report.archived_at = self._utcnow()
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return report

    def assert_text_integrity(self, report_id: int) -> None:
        for item in self.items(report_id):
            review = self._latest_editorial_review(item.id)
            if review is not None:
                ensure_editorial_text_integrity(
                    review.zh_title,
                    review.zh_summary,
                    review.review_recommendation,
                    review.evidence_assessment,
                )
        for item in self.overview_items(report_id):
            review = self._latest_overview_editorial_review(item.id)
            if review is not None:
                ensure_editorial_text_integrity(
                    review.zh_title,
                    review.zh_summary,
                    review.review_recommendation,
                    review.evidence_assessment,
                )

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

    def _report_for_update(self, report_id: int) -> DailyReportRecord:
        report = self.session.scalar(
            select(DailyReportRecord)
            .where(DailyReportRecord.id == report_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if report is None:
            self.session.rollback()
            raise LookupError("daily_report_not_found")
        return report

    def _trash_block_diagnostic(self, report_id: int) -> str | None:
        if self.session.scalar(
            select(DailyAutopilotRunRecord.id).where(
                DailyAutopilotRunRecord.daily_report_id == report_id,
                DailyAutopilotRunRecord.status.in_(("queued", "running")),
            )
        ) is not None:
            return "自动日报仍在处理中，完成或取消后才能删除。"

        if self._active_operation_owns_report("daily_report_audio", report_id):
            return "日报语音仍在处理中，完成或取消后才能删除。"

        active_audio = self.session.scalar(
            select(DailyReportAudioArtifactRecord.id)
            .join(
                OperationRunRecord,
                DailyReportAudioArtifactRecord.operation_run_id == OperationRunRecord.id,
                isouter=True,
            )
            .where(
                DailyReportAudioArtifactRecord.daily_report_id == report_id,
                (
                    DailyReportAudioArtifactRecord.status.in_(("queued", "running"))
                    | OperationRunRecord.status.in_(("queued", "running"))
                ),
            )
        )
        if active_audio is not None:
            return "日报语音仍在处理中，完成或取消后才能删除。"

        if self._active_operation_owns_report("daily_report_purge", report_id):
            return "日报清理仍在处理中，完成或取消后才能删除。"
        return None

    def _active_operation_owns_report(
        self, operation_type: str, report_id: int
    ) -> bool:
        operations = self.session.scalars(
            select(OperationRunRecord).where(
                OperationRunRecord.operation_type == operation_type,
                OperationRunRecord.status.in_(("queued", "running")),
            )
        )
        if any(
            _operation_owns_report(operation.requested_scope, report_id)
            for operation in operations
        ):
            return True
        return False

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

    def _automatic_reviews_complete(self, row: DailyReportChineseCandidate) -> bool:
        decision_complete = (
            row.decision_item_id is None
            or self._latest_editorial_review(row.decision_item_id) is not None
        )
        overview_complete = (
            row.overview_item_id is None
            or self._latest_overview_editorial_review(row.overview_item_id) is not None
        )
        return decision_complete and overview_complete

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


def _operation_owns_report(scope: object, report_id: int) -> bool:
    if not isinstance(scope, dict):
        return False
    for key in ("report_id", "daily_report_id"):
        if scope.get(key) == report_id:
            return True
    for key in ("report_ids", "daily_report_ids"):
        report_ids = scope.get(key)
        if isinstance(report_ids, (list, tuple)) and report_id in report_ids:
            return True
    return False


def rebuild_chinese_enrichment_summary(
    items: dict[str, dict[str, object]],
    *,
    candidate_total: int,
    model_budget: int,
) -> dict[str, object]:
    origins = Counter(
        row.get("origin") for row in items.values() if isinstance(row, dict)
    )
    errors: Counter[str] = Counter()
    for row in items.values():
        if not isinstance(row, dict):
            continue
        field_errors = _safe_field_errors(row.get("field_errors"))
        if field_errors:
            errors.update(field_errors)
        elif isinstance(row.get("error_code"), str):
            errors[row["error_code"]] += 1
    usage_ids = sorted(
        {
            usage_id
            for row in items.values()
            if isinstance(row, dict)
            for usage_id in row.get("model_usage_ids", [])
            if isinstance(usage_id, int)
            and not isinstance(usage_id, bool)
            and usage_id > 0
        }
    )
    return {
        "candidate_total": candidate_total,
        "model_budget": model_budget,
        "processed": len(items),
        "model_success": origins["model"],
        "partial_fallback": origins["model_partial"],
        "rule_fallback": origins["rule_fallback"],
        "budget_fallback": origins["budget_limit"],
        "error_counts": dict(sorted(errors.items())),
        "model_usage_ids": usage_ids,
        "items": items,
    }


def _safe_origin(value: object) -> str:
    if isinstance(value, str) and value in _SAFE_DAILY_CHINESE_ORIGINS:
        return value
    return "rule_fallback"


def _safe_error_code(value: object) -> str | None:
    return (
        value
        if isinstance(value, str) and value in DAILY_CHINESE_SAFE_ERROR_CODES
        else None
    )


def _safe_field_errors(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    safe: list[str] = []
    for item in value:
        if (
            isinstance(item, str)
            and item in DAILY_CHINESE_FIELD_ERROR_CODES
            and item not in safe
        ):
            safe.append(item)
        if len(safe) == 4:
            break
    return tuple(safe)


def _safe_model_name(value: object) -> str:
    return value if isinstance(value, str) and _SAFE_MODEL_NAME.fullmatch(value) else "unknown"


def _safe_usage_outcome(value: object) -> str:
    return value if isinstance(value, str) and value in _SAFE_DAILY_CHINESE_OUTCOMES else "fallback"


def _bounded_latency_ms(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and 0 <= number <= _MAX_MODEL_LATENCY_MS else None
