from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import OperationAttemptRecord, OperationEventRecord, OperationRunRecord


@dataclass(frozen=True, slots=True)
class OperationRow:
    operation_id: int
    operation_type: str
    status: str
    source_id: str | None
    progress_current: int
    progress_total: int | None
    created_at: datetime
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class OperationDetail:
    operation: OperationRow
    requested_scope: dict[str, object]
    attempts: tuple[OperationAttemptRecord, ...]
    events: tuple[OperationEventRecord, ...]


class OperationQueryService:
    def __init__(self, session: Session):
        self.session = session

    def list_recent(self, limit: int = 100) -> tuple[OperationRow, ...]:
        records = self.session.scalars(
            select(OperationRunRecord)
            .order_by(OperationRunRecord.id.desc())
            .limit(limit)
        ).all()
        return tuple(
            self._row(record)
            for record in records
        )

    def get(self, operation_id: int) -> OperationDetail | None:
        record = self.session.get(OperationRunRecord, operation_id)
        if record is None:
            return None
        attempts = tuple(
            self.session.scalars(
                select(OperationAttemptRecord)
                .where(OperationAttemptRecord.operation_run_id == operation_id)
                .order_by(OperationAttemptRecord.attempt_number.desc())
            )
        )
        events = tuple(
            self.session.scalars(
                select(OperationEventRecord)
                .where(OperationEventRecord.operation_run_id == operation_id)
                .order_by(OperationEventRecord.created_at.desc(), OperationEventRecord.id.desc())
                .limit(100)
            )
        )
        return OperationDetail(
            operation=self._row(record),
            requested_scope=dict(record.requested_scope),
            attempts=attempts,
            events=events,
        )

    @staticmethod
    def _row(record: OperationRunRecord) -> OperationRow:
        return OperationRow(
            operation_id=record.id,
            operation_type=record.operation_type,
            status=record.status,
            source_id=record.requested_scope.get("source_id"),
            progress_current=record.progress_current,
            progress_total=record.progress_total,
            created_at=record.created_at,
            error_code=record.error_code,
            error_message=record.error_message,
        )
