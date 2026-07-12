from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import OperationRunRecord


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
            OperationRow(
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
            for record in records
        )
