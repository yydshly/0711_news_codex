from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from json import dumps
from time import monotonic, sleep

from sqlalchemy.orm import Session

from newsradar.db.models import OperationRunRecord
from newsradar.operations.repository import OperationRepository
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.settings import Settings, get_settings


class OperationCommandService:
    """Shared Web and CLI command boundary for durable operations."""

    def __init__(
        self,
        session: Session,
        *,
        sleeper: Callable[[float], None] = sleep,
        clock: Callable[[], float] = monotonic,
        utcnow: Callable[[], datetime] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self._sleeper = sleeper
        self._clock = clock
        self._utcnow = utcnow or (lambda: datetime.now(UTC))
        self._settings = settings or get_settings()

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
        deadline_at = self._utcnow() + timedelta(seconds=self._settings.operation_timeout_seconds)
        record = OperationRepository(self.session).enqueue(
            OperationType.FETCH,
            {
                "source_id": source_id,
                "provider": provider,
                "dry_run": dry_run,
                "max_items": max_items,
                "one_off": one_off,
                "deadline_at": deadline_at.isoformat(),
            },
            trigger=trigger,
        )
        self.session.commit()
        return record.id

    def enqueue_event_pipeline(self, *, window_hours: int, trigger: str) -> int:
        if window_hours <= 0:
            raise ValueError("window_hours must be positive")
        now = self._utcnow()
        versions = {"relevance": "relevance-v1", "entities": "entities-v1", "cluster": "cluster-v1"}
        window_end = now.replace(minute=0, second=0, microsecond=0)
        key_parts = {
            "window_end": window_end.isoformat(),
            "window_hours": window_hours,
            "versions": versions,
        }
        scope = {
            "window_hours": window_hours,
            "algorithm_versions": versions,
            "window_end": window_end.isoformat(),
            "idempotency_key": "event-pipeline:"
            + sha256(dumps(key_parts, sort_keys=True).encode()).hexdigest(),
            "deadline_at": (
                now + timedelta(seconds=self._settings.operation_timeout_seconds)
            ).isoformat(),
        }
        record = OperationRepository(self.session).enqueue(
            OperationType.EVENT_PIPELINE, scope, trigger=trigger
        )
        self.session.commit()
        return record.id

    def enqueue_event_action(
        self, action: str, event_id: int, payload: dict | None, trigger: str
    ) -> int:
        operation_type = {
            "recluster": OperationType.EVENT_RECLUSTER,
            "enrich": OperationType.EVENT_ENRICH,
            "merge": OperationType.EVENT_MERGE,
            "split": OperationType.EVENT_SPLIT,
            "exclude": OperationType.EVENT_EXCLUDE,
        }.get(action)
        if operation_type is None or event_id <= 0:
            raise ValueError("invalid event action")
        now = self._utcnow()
        scope = {
            "event_id": event_id,
            "payload": payload or {},
            "idempotency_key": f"event-action:{action}:{event_id}:"
            + sha256(dumps(payload or {}, sort_keys=True).encode()).hexdigest(),
            "deadline_at": (
                now + timedelta(seconds=self._settings.operation_timeout_seconds)
            ).isoformat(),
        }
        record = OperationRepository(self.session).enqueue(operation_type, scope, trigger=trigger)
        self.session.commit()
        return record.id

    def retry(self, operation_id: int, *, trigger: str) -> int:
        original = self.session.get(OperationRunRecord, operation_id)
        terminal_statuses = {item.value for item in OperationStatus.terminal()}
        if original is None or original.status not in terminal_statuses:
            raise ValueError("operation is not retryable")
        scope = dict(original.requested_scope)
        scope["retry_of_operation_id"] = operation_id
        scope["deadline_at"] = (
            self._utcnow() + timedelta(seconds=self._settings.operation_timeout_seconds)
        ).isoformat()
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
