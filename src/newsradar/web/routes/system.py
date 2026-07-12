from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newsradar.db.models import OperationRunRecord, WorkerRecord


@dataclass(frozen=True, slots=True)
class SystemHealth:
    database_status: str
    migration_status: str
    worker_status: str
    queue_depth: int
    current_operation_count: int
    error_categories: tuple[tuple[str, int], ...]


def build_system_health(session: Session, *, now: datetime | None = None) -> SystemHealth:
    current_time = now or datetime.now(UTC)
    stale_before = current_time - timedelta(minutes=5)
    workers = list(session.scalars(select(WorkerRecord)))
    worker_status = "offline"
    if any(
        row.last_heartbeat_at and _as_utc(row.last_heartbeat_at) >= stale_before for row in workers
    ):
        worker_status = "online"
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
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
