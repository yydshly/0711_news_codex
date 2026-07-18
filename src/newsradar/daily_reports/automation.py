from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

REPORT_ZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class DueSchedule:
    schedule_date: date
    due_at: datetime


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def next_daily_run(now: datetime, daily_time: time) -> datetime:
    current = normalize_utc(now)
    local_now = current.astimezone(REPORT_ZONE)
    local_due = datetime.combine(local_now.date(), daily_time, tzinfo=REPORT_ZONE)
    if local_due <= local_now:
        local_due += timedelta(days=1)
    return local_due.astimezone(UTC)


def due_schedule(now: datetime, last_scheduled_date: date | None) -> DueSchedule | None:
    current = normalize_utc(now)
    local_now = current.astimezone(REPORT_ZONE)
    local_due = datetime.combine(local_now.date(), time(7, 30), tzinfo=REPORT_ZONE)
    if local_now < local_due or last_scheduled_date == local_now.date():
        return None
    return DueSchedule(
        schedule_date=local_now.date(),
        due_at=local_due.astimezone(UTC),
    )
