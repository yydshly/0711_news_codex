from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RETENTION_DAYS = 90
TRASH_DAYS = 30
TRASH_BATCH_LIMIT = 50

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
