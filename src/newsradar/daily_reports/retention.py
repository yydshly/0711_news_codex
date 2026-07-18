from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from newsradar.daily_reports.schema import REPORT_TIMEZONE

RETENTION_DAYS = 90
TRASH_DAYS = 30
TRASH_BATCH_LIMIT = 50
REPORT_ZONE = ZoneInfo(REPORT_TIMEZONE)

RetentionOutcome = Literal[
    "pinned",
    "unpinned",
    "trashed",
    "restored",
    "blocked",
    "unchanged",
]


@dataclass(frozen=True, slots=True)
class RetentionActionResult:
    report_id: int
    outcome: RetentionOutcome
    diagnostic_zh: str


def report_local_date(value: datetime) -> date:
    current = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return current.astimezone(REPORT_ZONE).date()
