from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        current = now or datetime.now(UTC)
        return max(0.0, (parsed.astimezone(UTC) - current.astimezone(UTC)).total_seconds())
