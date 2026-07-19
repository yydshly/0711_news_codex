from __future__ import annotations

import logging
import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import case, func, or_, select, text
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
    DailyReportRevisionCounterRecord,
    EventMergeCandidateRecord,
    ModelUsageRecord,
    OperationRunRecord,
)
from newsradar.event_merges.schema import MergeApplyResult

MAX_REVISION_ATTEMPTS = 3
logger = logging.getLogger(__name__)
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
        report, _ = self._create_draft(draft, commit=True)
        return report

    def begin_publication(
        self,
        report_date: date,
        *,
        source_operation_id: int,
    ) -> tuple[DailyReportRecord | None, DailyReportRecord | None]:
        """Lock one report day and resolve its idempotent draft or archived head."""
        self._lock_report_day(report_date)
        active_drafts = tuple(
            self.session.scalars(
                select(DailyReportRecord)
                .where(
                    DailyReportRecord.report_date == report_date,
                    DailyReportRecord.status == ReportStatus.DRAFT.value,
                    DailyReportRecord.deleted_at.is_(None),
                )
                .order_by(DailyReportRecord.revision.desc(), DailyReportRecord.id.desc())
            )
        )
        existing = next(
            (
                report
                for report in active_drafts
                if report.source_operation_id == source_operation_id
            ),
            None,
        )
        if existing is not None:
            return existing, None
        if active_drafts:
            self.session.rollback()
            raise RuntimeError("daily_report_publication_in_progress")
        predecessor = self.latest_archived_for_day(
            report_date,
            excluding_operation_id=source_operation_id,
        )
        return None, predecessor

    def create_cumulative_draft(self, draft: DailyReportDraft) -> DailyReportRecord:
        if draft.supersedes_report_id is None:
            raise ValueError("daily_report_cumulative_predecessor_required")

        def match_or_validate_predecessor() -> DailyReportRecord:
            self._lock_report_day(draft.report_date)
            existing = self._matching_report(
                draft,
                match_source_operation=True,
            )
            if existing is not None:
                return existing
            predecessor = self.latest_archived_for_day(
                draft.report_date,
                excluding_operation_id=draft.source_operation_id,
            )
            if (
                predecessor is None
                or predecessor.id != draft.supersedes_report_id
            ):
                self.session.rollback()
                raise RuntimeError("daily_report_cumulative_chain_changed")
            return predecessor

        predecessor = match_or_validate_predecessor()
        if predecessor.id != draft.supersedes_report_id:
            self.session.commit()
            return predecessor
        report, created = self._create_draft(
            draft,
            commit=False,
            match_source_operation=True,
            before_match=match_or_validate_predecessor,
        )
        if not created:
            self.session.commit()
            return report
        try:
            self._copy_revision_reviews(predecessor, report)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return report

    def _create_draft(
        self,
        draft: DailyReportDraft,
        *,
        commit: bool,
        match_source_operation: bool = False,
        before_match: Callable[[], object] | None = None,
    ) -> tuple[DailyReportRecord, bool]:
        validate_window_hours(draft.window_hours)
        for attempt in range(MAX_REVISION_ATTEMPTS):
            if before_match is not None:
                before_match()
            self._lock_revision(draft.report_date, draft.window_hours)
            existing = self._matching_report(
                draft,
                match_source_operation=match_source_operation,
            )
            if existing is not None:
                if commit:
                    self.session.commit()
                return existing, False

            revision = self._next_revision(draft.report_date, draft.window_hours)
            if draft.supersedes_report_id is not None:
                predecessor = self.session.get(
                    DailyReportRecord, draft.supersedes_report_id
                )
                if predecessor is not None:
                    revision = max(revision, predecessor.revision + 1)
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
                self._record_revision_high_water(
                    draft.report_date,
                    draft.window_hours,
                    revision,
                )
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
                if commit:
                    self.session.commit()
                return report, True
            except IntegrityError as error:
                self.session.rollback()
                if not self._is_revision_conflict(error):
                    raise
                if before_match is not None:
                    before_match()
                self._lock_revision(draft.report_date, draft.window_hours)
                existing = self._matching_report(
                    draft,
                    match_source_operation=match_source_operation,
                )
                if existing is not None:
                    if commit:
                        self.session.commit()
                    return existing, False
                self.session.rollback()
                if attempt == MAX_REVISION_ATTEMPTS - 1:
                    raise RuntimeError("daily_report_revision_conflict") from error

        raise RuntimeError("daily_report_revision_conflict")

    def latest_archived_for_day(
        self,
        report_date: date,
        *,
        excluding_operation_id: int,
    ) -> DailyReportRecord | None:
        return self.session.scalar(
            select(DailyReportRecord)
            .where(
                DailyReportRecord.report_date == report_date,
                DailyReportRecord.status == ReportStatus.ARCHIVED.value,
                DailyReportRecord.deleted_at.is_(None),
                DailyReportRecord.source_operation_id != excluding_operation_id,
            )
            .order_by(DailyReportRecord.revision.desc(), DailyReportRecord.id.desc())
            .limit(1)
        )

    def applied_event_survivors(self, event_ids: set[int]) -> dict[int, int]:
        requested = frozenset(event_ids)
        survivors = {event_id: event_id for event_id in requested}
        if not requested:
            return survivors
        edges = self._applied_merge_edges_for(requested)
        for event_id in requested:
            resolved = self._resolve_merge_survivor(event_id, edges)
            if resolved is not None:
                survivors[event_id] = resolved
        return survivors

    def _applied_merge_edges_for(self, event_ids: frozenset[int]) -> dict[int, int]:
        """Load only merge records connected to the report's event frontier."""
        edges: dict[int, int] = {}
        conflicted_legacy_ids: set[int] = set()
        frontier = set(event_ids)
        visited: set[int] = set()
        while frontier:
            records = self.session.scalars(
                select(EventMergeCandidateRecord).where(
                    EventMergeCandidateRecord.status == "applied",
                    or_(
                        EventMergeCandidateRecord.left_event_id.in_(frontier),
                        EventMergeCandidateRecord.right_event_id.in_(frontier),
                    ),
                )
            )
            connected: set[int] = set()
            for record in records:
                try:
                    result = MergeApplyResult.model_validate(record.result_summary)
                except (TypeError, ValidationError):
                    self._warn_invalid_merge_summary(record.id, "validation_error")
                    continue
                if not self._complete_applied_merge_result(record, result):
                    self._warn_invalid_merge_summary(record.id, "incomplete_result")
                    continue
                legacy_event_id = result.legacy_event_id
                survivor_event_id = result.survivor_event_id
                assert legacy_event_id is not None
                assert survivor_event_id is not None
                connected.update((legacy_event_id, survivor_event_id))
                existing = edges.get(legacy_event_id)
                if existing is not None and existing != survivor_event_id:
                    conflicted_legacy_ids.add(legacy_event_id)
                    edges.pop(legacy_event_id, None)
                    self._warn_invalid_merge_summary(record.id, "conflicting_survivor")
                elif legacy_event_id not in conflicted_legacy_ids:
                    edges[legacy_event_id] = survivor_event_id
            visited.update(frontier)
            frontier = connected - visited
        return edges

    def _resolve_merge_survivor(
        self, event_id: int, edges: dict[int, int]
    ) -> int | None:
        current = event_id
        visited: set[int] = set()
        while current in edges:
            if current in visited:
                self._warn_invalid_merge_summary(current, "cyclic_survivor")
                return None
            visited.add(current)
            current = edges[current]
        return current

    @staticmethod
    def _complete_applied_merge_result(
        record: EventMergeCandidateRecord,
        result: MergeApplyResult,
    ) -> bool:
        if (
            result.status not in {"applied", "succeeded"}
            or result.candidate_id != record.id
            or result.survivor_event_id is None
            or result.survivor_version_number is None
            or result.legacy_event_id is None
            or result.legacy_version_number is None
            or result.survivor_event_id <= 0
            or result.survivor_version_number <= 0
            or result.legacy_event_id <= 0
            or result.legacy_version_number <= 0
        ):
            return False
        return {result.survivor_event_id, result.legacy_event_id} == {
            record.left_event_id,
            record.right_event_id,
        }

    @staticmethod
    def _warn_invalid_merge_summary(candidate_id: int, error_code: str) -> None:
        logger.warning(
            "invalid applied event merge result ignored",
            extra={"candidate_id": candidate_id, "error_code": error_code},
        )

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
        identity = self.session.get(
            DailyReportRecord, report_id, populate_existing=True
        )
        if identity is None:
            self.session.rollback()
            raise LookupError("daily_report_not_found")
        report_date = identity.report_date
        window_hours = identity.window_hours
        self._lock_revision(report_date, window_hours)
        report = self._report_for_update(report_id)
        if report.deleted_at is None:
            self.session.commit()
            return RetentionActionResult(report_id, "unchanged", "日报不在回收站中。")
        conflict = self._restore_conflict(report)
        if conflict is not None:
            self.session.commit()
            return self._restore_blocked(report_id)
        report.deleted_at = None
        report.purge_after = None
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            if not self._is_revision_conflict(error):
                raise
            self._lock_revision(report_date, window_hours)
            report = self._report_for_update(report_id)
            if self._restore_conflict(report) is None:
                self.session.rollback()
                raise
            self.session.commit()
            return self._restore_blocked(report_id)
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

    def overview_decisions(
        self, report_id: int
    ) -> dict[tuple[int, int], EditorialDecision]:
        return {
            (item.event_id, item.event_version_number): EditorialDecision(review.decision)
            for item in self.overview_items(report_id)
            if (review := self._latest_overview_editorial_review(item.id)) is not None
        }

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
        rebuilt_overview_items: tuple[DailyReportOverviewItemDraft, ...] | None = None,
        generation_summary: dict[str, object] | None = None,
        expected_source_report_id: int | None = None,
    ) -> DailyReportRecord:
        selected = self._revision_source(report_id)
        self._lock_revision(selected.report_date, selected.window_hours)
        original = self.revision_target(report_id)
        if original.status == ReportStatus.DRAFT.value:
            self.session.commit()
            return original
        if (
            expected_source_report_id is not None
            and original.id != expected_source_report_id
        ):
            self.session.rollback()
            raise RuntimeError("daily_report_revision_chain_changed")
        original_overview_items = self.overview_items(original.id)
        overview_items = (
            rebuilt_overview_items
            if rebuilt_overview_items is not None
            else tuple(
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
        revision, created = self._create_draft(
            DailyReportDraft(
                report_date=original.report_date,
                window_hours=original.window_hours,
                window_start=original.window_start,
                window_end=original.window_end,
                source_operation_id=original.source_operation_id,
                generation_summary=(
                    dict(generation_summary)
                    if generation_summary is not None
                    else dict(original.generation_summary)
                ),
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
            ),
            commit=False,
        )
        if not created:
            self.session.commit()
            return revision
        try:
            self._copy_revision_reviews(original, revision)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return revision

    def _copy_revision_reviews(
        self, original: DailyReportRecord, revision: DailyReportRecord
    ) -> None:
        original_decision_by_event = {
            (row.event_id, row.event_version_number): row
            for row in self.items(original.id)
        }
        revision_decision_by_event = {
            (row.event_id, row.event_version_number): row
            for row in self.items(revision.id)
        }
        for event_key, original_item in original_decision_by_event.items():
            revision_item = revision_decision_by_event.get(event_key)
            if revision_item is None:
                continue
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
        revision_overview_by_event_id: dict[
            int, list[DailyReportOverviewItemRecord]
        ] = {}
        for row in revision_overview_by_event.values():
            revision_overview_by_event_id.setdefault(row.event_id, []).append(row)
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
                    same_event_targets = revision_overview_by_event_id.get(
                        original_target.event_id, []
                    )
                    if len(same_event_targets) != 1:
                        raise ValueError(
                            "invalid_daily_report_overview_duplicate_target"
                        )
                    revision_target = same_event_targets[0]
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

    def revision_target(self, report_id: int) -> DailyReportRecord:
        report = self._revision_source(report_id)

        visited: set[int] = set()
        current = report
        while True:
            if current.id in visited:
                raise RuntimeError("daily_report_revision_chain_invalid")
            visited.add(current.id)
            successor = self.session.scalar(
                select(DailyReportRecord)
                .where(
                    DailyReportRecord.supersedes_report_id == current.id,
                    DailyReportRecord.deleted_at.is_(None),
                )
                .execution_options(populate_existing=True)
            )
            if successor is None:
                return current
            current = successor

    def _revision_source(self, report_id: int) -> DailyReportRecord:
        report = self.session.get(
            DailyReportRecord, report_id, populate_existing=True
        )
        if report is None:
            raise LookupError("daily_report_not_found")
        if report.deleted_at is not None:
            raise ValueError("daily_report_is_trashed")
        if report.status != ReportStatus.ARCHIVED.value:
            raise ValueError("daily_report_must_be_archived")
        return report

    def _lock_revision(self, report_date: date, window_hours: int) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            return
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"newsradar:daily-report:{report_date.isoformat()}:{window_hours}"},
        )

    def _lock_report_day(self, report_date: date) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            return
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"newsradar:daily-report-day:{report_date.isoformat()}"},
        )

    def _next_revision(self, report_date: date, window_hours: int) -> int:
        counter = self.session.get(
            DailyReportRevisionCounterRecord,
            (report_date, window_hours),
            populate_existing=True,
        )
        stored_high_water = counter.highest_revision if counter is not None else 0
        existing_high_water = int(
            self.session.scalar(
                select(func.max(DailyReportRecord.revision)).where(
                    DailyReportRecord.report_date == report_date,
                    DailyReportRecord.window_hours == window_hours,
                )
            )
            or 0
        )
        return max(stored_high_water, existing_high_water) + 1

    def _record_revision_high_water(
        self,
        report_date: date,
        window_hours: int,
        revision: int,
    ) -> None:
        counter = self.session.get(
            DailyReportRevisionCounterRecord,
            (report_date, window_hours),
            populate_existing=True,
        )
        if counter is None:
            self.session.add(
                DailyReportRevisionCounterRecord(
                    report_date=report_date,
                    window_hours=window_hours,
                    highest_revision=revision,
                )
            )
        elif revision > counter.highest_revision:
            counter.highest_revision = revision
        self.session.flush()

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

    def _restore_conflict(self, report: DailyReportRecord) -> int | None:
        if report.supersedes_report_id is not None:
            return self.session.scalar(
                select(DailyReportRecord.id).where(
                    DailyReportRecord.id != report.id,
                    DailyReportRecord.supersedes_report_id
                    == report.supersedes_report_id,
                    DailyReportRecord.deleted_at.is_(None),
                )
            )
        return self.session.scalar(
            select(DailyReportRecord.id).where(
                DailyReportRecord.id != report.id,
                DailyReportRecord.report_date == report.report_date,
                DailyReportRecord.window_hours == report.window_hours,
                DailyReportRecord.source_operation_id == report.source_operation_id,
                DailyReportRecord.supersedes_report_id.is_(None),
                DailyReportRecord.deleted_at.is_(None),
            )
        )

    @staticmethod
    def _restore_blocked(report_id: int) -> RetentionActionResult:
        return RetentionActionResult(
            report_id,
            "blocked",
            "该日报已有新的有效修订版，不能直接恢复。",
        )

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

    def _matching_report(
        self,
        draft: DailyReportDraft,
        *,
        match_source_operation: bool = False,
    ) -> DailyReportRecord | None:
        if draft.supersedes_report_id is not None:
            statement = select(DailyReportRecord).where(
                DailyReportRecord.supersedes_report_id == draft.supersedes_report_id,
                DailyReportRecord.deleted_at.is_(None),
            )
            if match_source_operation:
                statement = statement.where(
                    DailyReportRecord.source_operation_id == draft.source_operation_id
                )
            return self.session.scalar(statement)
        return self.session.scalar(
            select(DailyReportRecord).where(
                DailyReportRecord.report_date == draft.report_date,
                DailyReportRecord.window_hours == draft.window_hours,
                DailyReportRecord.source_operation_id == draft.source_operation_id,
                DailyReportRecord.supersedes_report_id.is_(None),
                DailyReportRecord.deleted_at.is_(None),
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
