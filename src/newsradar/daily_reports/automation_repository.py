from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from newsradar.daily_reports.automation import (
    DueSchedule,
    due_schedule,
    next_daily_run,
    normalize_utc,
)
from newsradar.daily_reports.retention import (
    RETENTION_DAYS,
    TRASH_BATCH_LIMIT,
    TRASH_DAYS,
    report_local_date,
)
from newsradar.db.models import DailyAutomationConfigRecord, DailyReportRecord

PURGE_BATCH_LIMIT = 20


class DailyAutomationRepository:
    def __init__(
        self,
        session: Session,
        *,
        utcnow: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self._utcnow = utcnow or (lambda: datetime.now(UTC))

    def get_or_create(self) -> DailyAutomationConfigRecord:
        config = self.session.get(DailyAutomationConfigRecord, 1)
        if config is not None:
            self._normalize_config(config)
            return config
        now = normalize_utc(self._utcnow())
        config = DailyAutomationConfigRecord(
            id=1,
            enabled=False,
            timezone="Asia/Shanghai",
            daily_time="07:30",
            window_hours=24,
            resource_profile="standard",
            next_run_at=next_daily_run(now, time(7, 30)),
            created_at=now,
            updated_at=now,
        )
        self.session.add(config)
        self.session.flush()
        return config

    def enable(self) -> DailyAutomationConfigRecord:
        config = self.get_or_create()
        now = normalize_utc(self._utcnow())
        config.enabled = True
        config.next_run_at = next_daily_run(now, self._daily_time(config))
        config.updated_at = now
        self.session.flush()
        return config

    def pause(self) -> DailyAutomationConfigRecord:
        config = self.get_or_create()
        config.enabled = False
        config.updated_at = normalize_utc(self._utcnow())
        self.session.flush()
        return config

    def lock_due(self) -> DueSchedule | None:
        self.get_or_create()
        if self.session.get_bind().dialect.name == "postgresql":
            self.session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtext('newsradar:daily-automation-due'))"
                )
            )
        config = self.session.scalar(
            select(DailyAutomationConfigRecord)
            .where(DailyAutomationConfigRecord.id == 1)
            .with_for_update()
        )
        if config is None or not config.enabled:
            return None
        self._normalize_config(config)
        return due_schedule(normalize_utc(self._utcnow()), config.last_scheduled_date)

    def lock_retention(self) -> DailyAutomationConfigRecord | None:
        self.get_or_create()
        if self.session.get_bind().dialect.name == "postgresql":
            self.session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtext('newsradar:daily-retention-sweep'))"
                )
            )
        config = self.session.scalar(
            select(DailyAutomationConfigRecord)
            .where(DailyAutomationConfigRecord.id == 1)
            .with_for_update()
        )
        if config is None:
            raise LookupError("daily_automation_not_found")
        if config.last_retention_date == report_local_date(self._utcnow()):
            return None
        return config

    def trash_retention_candidates(self) -> tuple[int, ...]:
        now = normalize_utc(self._utcnow())
        retention_start = report_local_date(now) - timedelta(days=RETENTION_DAYS)
        reports = tuple(
            self.session.scalars(
                select(DailyReportRecord)
                .where(
                    DailyReportRecord.deleted_at.is_(None),
                    DailyReportRecord.pinned_at.is_(None),
                    DailyReportRecord.report_date <= retention_start,
                )
                .order_by(DailyReportRecord.report_date, DailyReportRecord.id)
                .limit(TRASH_BATCH_LIMIT)
                .with_for_update()
            )
        )
        for report in reports:
            if report.pinned_at is None and report.deleted_at is None:
                report.deleted_at = now
                report.purge_after = now + timedelta(days=TRASH_DAYS)
        self.session.flush()
        return tuple(report.id for report in reports if report.deleted_at == now)

    def purge_retention_candidates(self) -> tuple[int, ...]:
        now = normalize_utc(self._utcnow())
        return tuple(
            self.session.scalars(
                select(DailyReportRecord.id)
                .where(
                    DailyReportRecord.deleted_at.is_not(None),
                    DailyReportRecord.pinned_at.is_(None),
                    DailyReportRecord.purge_after <= now,
                )
                .order_by(DailyReportRecord.purge_after, DailyReportRecord.id)
                .limit(PURGE_BATCH_LIMIT)
                .with_for_update()
            )
        )

    def mark_retention_swept(
        self, config: DailyAutomationConfigRecord
    ) -> DailyAutomationConfigRecord:
        now = normalize_utc(self._utcnow())
        config.last_retention_date = report_local_date(now)
        config.updated_at = now
        self.session.flush()
        return config

    def mark_scheduled(self, due: DueSchedule, *, run_id: int) -> DailyAutomationConfigRecord:
        config = self.session.scalar(
            select(DailyAutomationConfigRecord)
            .where(DailyAutomationConfigRecord.id == 1)
            .with_for_update()
        )
        if config is None:
            raise LookupError("daily_automation_not_found")
        self._normalize_config(config)
        now = normalize_utc(self._utcnow())
        current_due = due_schedule(now, config.last_scheduled_date)
        if current_due is None or current_due.schedule_date != due.schedule_date:
            raise ValueError("daily_automation_schedule_not_due")
        config.last_scheduled_date = due.schedule_date
        config.last_run_id = run_id
        config.next_run_at = next_daily_run(now, self._daily_time(config))
        config.updated_at = now
        self.session.flush()
        return config

    @staticmethod
    def _daily_time(config: DailyAutomationConfigRecord) -> time:
        return time.fromisoformat(config.daily_time)

    @staticmethod
    def _normalize_config(config: DailyAutomationConfigRecord) -> None:
        config.next_run_at = normalize_utc(config.next_run_at)
