from __future__ import annotations

from collections.abc import Callable
from time import monotonic, sleep

from sqlalchemy.orm import Session

from newsradar.db.models import OperationRunRecord
from newsradar.operations.repository import OperationRepository
from newsradar.operations.schema import OperationStatus, OperationType


class OperationCommandService:
    """Shared Web and CLI command boundary for durable operations."""

    def __init__(
        self,
        session: Session,
        *,
        sleeper: Callable[[float], None] = sleep,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.session = session
        self._sleeper = sleeper
        self._clock = clock

    def enqueue_fetch(
        self,
        *,
        source_id: str,
        provider: str | None = None,
        dry_run: bool = False,
        max_items: int | None = None,
        one_off: bool = False,
        trigger: str,
    ) -> int:
        record = OperationRepository(self.session).enqueue(
            OperationType.FETCH,
            {
                "source_id": source_id,
                "provider": provider,
                "dry_run": dry_run,
                "max_items": max_items,
                "one_off": one_off,
            },
            trigger=trigger,
        )
        self.session.commit()
        return record.id

    def retry(self, operation_id: int, *, trigger: str) -> int:
        original = self.session.get(OperationRunRecord, operation_id)
        terminal_statuses = {item.value for item in OperationStatus.terminal()}
        if original is None or original.status not in terminal_statuses:
            raise ValueError("operation is not retryable")
        scope = dict(original.requested_scope)
        scope["retry_of_operation_id"] = operation_id
        record = OperationRepository(self.session).enqueue(
            OperationType(original.operation_type), scope, trigger=trigger
        )
        self.session.commit()
        return record.id

    def cancel(self, operation_id: int) -> bool:
        result = OperationRepository(self.session).request_cancel(operation_id)
        self.session.commit()
        return result

    def wait_for_terminal(
        self, operation_id: int, *, timeout_seconds: float = 1800, poll_seconds: float = 0.25
    ) -> OperationRunRecord:
        deadline = self._clock() + timeout_seconds
        terminal_statuses = {item.value for item in OperationStatus.terminal()}
        while self._clock() < deadline:
            self.session.expire_all()
            record = self.session.get(OperationRunRecord, operation_id)
            if record is None:
                raise LookupError(operation_id)
            if record.status in terminal_statuses:
                return record
            self._sleeper(poll_seconds)
        raise TimeoutError(f"operation {operation_id} did not finish within {timeout_seconds}s")
