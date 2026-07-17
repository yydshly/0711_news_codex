from __future__ import annotations

import re

TEXT_INTEGRITY_ERROR = "daily_report_text_corrupted"
_SUSPICIOUS_QUESTION_RUN = re.compile(r"\?{4,}")


def has_suspicious_question_run(value: str) -> bool:
    return bool(_SUSPICIOUS_QUESTION_RUN.search(value))


def ensure_editorial_text_integrity(*values: str) -> None:
    if any(has_suspicious_question_run(value) for value in values):
        raise ValueError(TEXT_INTEGRITY_ERROR)
