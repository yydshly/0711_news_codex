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


def validate_window_hours(value: int) -> int:
    if isinstance(value, bool) or value not in ALLOWED_WINDOW_HOURS:
        raise ValueError("invalid_daily_report_window")
    return value


@dataclass(frozen=True, slots=True)
class DailyReportItemDraft:
    event_id: int
    event_version_number: int
    section: ReportSection
    position: int
    snapshot: dict[str, Any]
    included: bool = True


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
