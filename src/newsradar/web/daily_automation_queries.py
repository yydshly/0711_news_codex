"""Read model for the local daily-report automation console."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.daily_reports.automation import normalize_utc
from newsradar.daily_reports.automation_repository import DailyAutomationRepository
from newsradar.db.models import (
    DailyAutopilotRunRecord,
    OperationRunRecord,
    WorkerRecord,
)
from newsradar.web.daily_autopilot_queries import DailyAutopilotSummaryView

_RESOURCE_PROFILE_ZH = {
    "standard": "标准资源配置",
    "power_saver": "节能资源配置",
}


@dataclass(frozen=True, slots=True)
class DailyAutomationView:
    enabled: bool
    status_zh: str
    daily_time: str
    timezone: str
    window_hours: int
    resource_profile_zh: str
    next_run_at: datetime
    last_run: DailyAutopilotSummaryView | None
    active_run: DailyAutopilotSummaryView | None
    worker_online: bool
    diagnostic: str


class DailyAutomationQueryService:
    def __init__(
        self,
        session: Session,
        *,
        utcnow: Callable[[], datetime] | None = None,
        worker_lease_seconds: float = 60,
    ) -> None:
        self.session = session
        self._utcnow = utcnow or (lambda: datetime.now(UTC))
        self.worker_lease_seconds = worker_lease_seconds

    def view(self) -> DailyAutomationView:
        config = DailyAutomationRepository(self.session, utcnow=self._utcnow).get_or_create()
        active_run = self.session.scalar(
            select(DailyAutopilotRunRecord)
            .where(DailyAutopilotRunRecord.status.in_(("queued", "running")))
            .order_by(
                DailyAutopilotRunRecord.updated_at.desc(),
                DailyAutopilotRunRecord.id.desc(),
            )
            .limit(1)
        )
        last_run = (
            self.session.get(DailyAutopilotRunRecord, config.last_run_id)
            if config.last_run_id is not None
            else None
        )
        worker_online = self._worker_online()
        return DailyAutomationView(
            enabled=config.enabled,
            status_zh="已启用" if config.enabled else "已暂停",
            daily_time=config.daily_time,
            timezone=config.timezone,
            window_hours=config.window_hours,
            resource_profile_zh=_RESOURCE_PROFILE_ZH.get(config.resource_profile, "未知资源配置"),
            next_run_at=normalize_utc(config.next_run_at),
            last_run=_run_view(last_run),
            active_run=_run_view(active_run),
            worker_online=worker_online,
            diagnostic="调度服务在线" if worker_online else "调度服务离线",
        )

    def _worker_online(self) -> bool:
        newest_worker_heartbeat = self.session.scalar(
            select(WorkerRecord.last_heartbeat_at)
            .where(WorkerRecord.last_heartbeat_at.is_not(None))
            .order_by(WorkerRecord.last_heartbeat_at.desc())
            .limit(1)
        )
        newest_operation_heartbeat = self.session.scalar(
            select(OperationRunRecord.heartbeat_at)
            .where(
                OperationRunRecord.status == "running",
                OperationRunRecord.heartbeat_at.is_not(None),
            )
            .order_by(
                OperationRunRecord.heartbeat_at.desc(),
                OperationRunRecord.id.desc(),
            )
            .limit(1)
        )
        cutoff = normalize_utc(self._utcnow()) - timedelta(seconds=2 * self.worker_lease_seconds)
        return any(
            normalize_utc(heartbeat) > cutoff
            for heartbeat in (newest_worker_heartbeat, newest_operation_heartbeat)
            if heartbeat is not None
        )


def _run_view(
    run: DailyAutopilotRunRecord | None,
) -> DailyAutopilotSummaryView | None:
    if run is None:
        return None
    return DailyAutopilotSummaryView(
        run_id=run.id,
        status=run.status,
        stage=run.stage,
        window_hours=run.window_hours,
        created_at=run.created_at,
        updated_at=run.updated_at,
        daily_report_id=run.daily_report_id,
    )
