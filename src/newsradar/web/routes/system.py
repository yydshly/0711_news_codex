from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newsradar.ai.health import check_minimax_config
from newsradar.db.models import ModelUsageRecord, OperationRunRecord, WorkerRecord
from newsradar.settings import Settings


@dataclass(frozen=True, slots=True)
class SystemHealth:
    database_status: str
    migration_status: str
    worker_status: str
    queue_depth: int
    current_operation_count: int
    error_categories: tuple[tuple[str, int], ...]
    online_worker_count: int
    idle_worker_count: int
    busy_worker_count: int
    stale_worker_count: int
    last_worker_heartbeat_at: datetime | None


@dataclass(frozen=True, slots=True)
class MiniMaxRuntimeView:
    configured: bool
    region: str
    fast_model: str
    deep_model: str
    usage_count: int
    success_count: int
    latest_outcome: str | None
    latest_used_at: datetime | None


def build_system_health(session: Session, *, now: datetime | None = None) -> SystemHealth:
    current_time = now or datetime.now(UTC)
    stale_before = current_time - timedelta(minutes=5)
    workers = list(session.scalars(select(WorkerRecord)))
    online_workers = [
        row
        for row in workers
        if row.last_heartbeat_at and _as_utc(row.last_heartbeat_at) >= stale_before
    ]
    idle_worker_count = sum(row.status == "idle" for row in online_workers)
    busy_worker_count = sum(row.status == "running" for row in online_workers)
    stale_worker_count = len(workers) - len(online_workers)
    worker_status = "offline"
    if busy_worker_count:
        worker_status = "busy"
    elif idle_worker_count:
        worker_status = "idle"
    elif workers:
        worker_status = "stale"
    error_categories = tuple(
        (str(code), int(count))
        for code, count in session.execute(
            select(OperationRunRecord.error_code, func.count())
            .where(
                OperationRunRecord.status == "failed",
                OperationRunRecord.error_code.is_not(None),
            )
            .group_by(OperationRunRecord.error_code)
            .order_by(func.count().desc(), OperationRunRecord.error_code)
            .limit(10)
        )
    )
    return SystemHealth(
        database_status="online",
        migration_status="current",
        worker_status=worker_status,
        queue_depth=session.scalar(
            select(func.count())
            .select_from(OperationRunRecord)
            .where(OperationRunRecord.status == "queued")
        ) or 0,
        current_operation_count=session.scalar(
            select(func.count())
            .select_from(OperationRunRecord)
            .where(OperationRunRecord.status == "running")
        ) or 0,
        error_categories=error_categories,
        online_worker_count=len(online_workers),
        idle_worker_count=idle_worker_count,
        busy_worker_count=busy_worker_count,
        stale_worker_count=stale_worker_count,
        last_worker_heartbeat_at=max(
            (row.last_heartbeat_at for row in workers if row.last_heartbeat_at), default=None
        ),
    )


def build_minimax_runtime_view(session: Session, settings: Settings) -> MiniMaxRuntimeView:
    config = check_minimax_config(settings)
    usages = list(
        session.scalars(select(ModelUsageRecord).order_by(ModelUsageRecord.created_at.desc()).limit(1))
    )
    latest = usages[0] if usages else None
    return MiniMaxRuntimeView(
        configured=config.configured,
        region=config.region,
        fast_model=config.fast_model,
        deep_model=config.deep_model,
        usage_count=session.scalar(select(func.count()).select_from(ModelUsageRecord)) or 0,
        success_count=session.scalar(
            select(func.count())
            .select_from(ModelUsageRecord)
            .where(ModelUsageRecord.outcome == "success")
        )
        or 0,
        latest_outcome=latest.outcome if latest else None,
        latest_used_at=latest.created_at if latest else None,
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
