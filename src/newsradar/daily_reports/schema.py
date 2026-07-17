from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

ALLOWED_WINDOW_HOURS = frozenset({24, 48, 72})
MAX_ITEMS_PER_SECTION = 20
REPORT_TIMEZONE = "Asia/Shanghai"


class ReportStatus(StrEnum):
    DRAFT = "draft"
    ARCHIVED = "archived"


class ReportSection(StrEnum):
    CONFIRMED = "confirmed"
    EMERGING = "emerging"


class EditorialDecision(StrEnum):
    KEEP = "keep"
    NEEDS_EVIDENCE = "needs_evidence"
    EXCLUDE = "exclude"
    DUPLICATE = "duplicate"


def validate_window_hours(value: int) -> int:
    if isinstance(value, bool) or value not in ALLOWED_WINDOW_HOURS:
        raise ValueError("invalid_daily_report_window")
    return value


def _editorial_text(value: str, maximum_length: int, error_code: str) -> str:
    if not isinstance(value, str):
        raise ValueError(error_code)
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum_length:
        raise ValueError(error_code)
    return cleaned


@dataclass(frozen=True, slots=True)
class DailyReportItemDraft:
    event_id: int
    event_version_number: int
    section: ReportSection
    position: int
    snapshot: dict[str, Any]
    included: bool = True


@dataclass(frozen=True, slots=True)
class DailyReportOverviewItemDraft:
    event_id: int
    event_version_number: int
    position: int
    snapshot: dict[str, Any]
    decision_event_id: int | None = None


@dataclass(frozen=True, slots=True)
class DailyReportOverviewEditorialReviewDraft:
    decision: EditorialDecision
    zh_title: str
    zh_summary: str
    review_recommendation: str
    evidence_assessment: str
    duplicate_of_overview_item_id: int | None

    @classmethod
    def create(
        cls,
        *,
        decision: str,
        zh_title: str,
        zh_summary: str,
        review_recommendation: str,
        evidence_assessment: str,
        duplicate_of_overview_item_id: int | str | None = None,
    ) -> DailyReportOverviewEditorialReviewDraft:
        try:
            parsed_decision = EditorialDecision(decision)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid_daily_report_editorial_decision") from error
        duplicate_target = _overview_duplicate_target(duplicate_of_overview_item_id)
        if (
            parsed_decision is EditorialDecision.DUPLICATE
            and duplicate_target is None
        ) or (
            parsed_decision is not EditorialDecision.DUPLICATE
            and duplicate_target is not None
        ):
            raise ValueError("invalid_daily_report_overview_duplicate_target")
        return cls(
            decision=parsed_decision,
            zh_title=_editorial_text(
                zh_title, 240, "invalid_daily_report_editorial_title"
            ),
            zh_summary=_editorial_text(
                zh_summary, 4000, "invalid_daily_report_editorial_summary"
            ),
            review_recommendation=_editorial_text(
                review_recommendation,
                2000,
                "invalid_daily_report_editorial_recommendation",
            ),
            evidence_assessment=_editorial_text(
                evidence_assessment,
                2000,
                "invalid_daily_report_editorial_evidence_assessment",
            ),
            duplicate_of_overview_item_id=duplicate_target,
        )


@dataclass(frozen=True, slots=True)
class DailyReportEditorialReviewDraft:
    decision: EditorialDecision
    zh_title: str
    zh_summary: str
    review_recommendation: str
    evidence_assessment: str

    @classmethod
    def create(
        cls,
        *,
        decision: str,
        zh_title: str,
        zh_summary: str,
        review_recommendation: str,
        evidence_assessment: str,
    ) -> DailyReportEditorialReviewDraft:
        try:
            parsed_decision = EditorialDecision(decision)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid_daily_report_editorial_decision") from error
        return cls(
            decision=parsed_decision,
            zh_title=_editorial_text(zh_title, 240, "invalid_daily_report_editorial_title"),
            zh_summary=_editorial_text(
                zh_summary, 4000, "invalid_daily_report_editorial_summary"
            ),
            review_recommendation=_editorial_text(
                review_recommendation, 2000, "invalid_daily_report_editorial_recommendation"
            ),
            evidence_assessment=_editorial_text(
                evidence_assessment, 2000, "invalid_daily_report_editorial_evidence_assessment"
            ),
        )


def _overview_duplicate_target(value: int | str | None) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("invalid_daily_report_overview_duplicate_target")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        cleaned = value.strip()
        if not cleaned.isascii() or not cleaned.isdecimal():
            raise ValueError("invalid_daily_report_overview_duplicate_target")
        parsed = int(cleaned)
    else:
        raise ValueError("invalid_daily_report_overview_duplicate_target")
    if parsed <= 0:
        raise ValueError("invalid_daily_report_overview_duplicate_target")
    return parsed


@dataclass(frozen=True, slots=True)
class DailyReportDraft:
    report_date: date
    window_hours: int
    window_start: datetime
    window_end: datetime
    source_operation_id: int
    generation_summary: dict[str, Any]
    items: tuple[DailyReportItemDraft, ...]
    overview_items: tuple[DailyReportOverviewItemDraft, ...] = ()
    supersedes_report_id: int | None = None
