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


@dataclass(frozen=True, slots=True)
class DailyReportDraft:
    report_date: date
    window_hours: int
    window_start: datetime
    window_end: datetime
    source_operation_id: int
    generation_summary: dict[str, Any]
    items: tuple[DailyReportItemDraft, ...]
    supersedes_report_id: int | None = None
