from __future__ import annotations

import random
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    OperationAttemptRecord,
    OperationEventRecord,
    OperationRunRecord,
    WorkerRecord,
)
from newsradar.operations.logging import redact
from newsradar.operations.schema import OperationStatus, OperationType

MAX_ATTEMPTS = 3
MAX_OPERATION_TRIGGER_LENGTH = 16


@dataclass(frozen=True)
class OperationLease:
    operation_id: int
    attempt_id: int
    attempt_number: int
    worker_id: str
    requested_scope: dict[str, Any]
    operation_type: str = "fetch"


class OperationRepository:
    """Durable operation queue operations in short, independently committed transactions."""

    def __init__(
        self, session: Session, *, retry_jitter: Callable[[float], float] | None = None
    ):
        self.session = session
        self._retry_jitter = retry_jitter or (lambda bound: random.uniform(0, bound))

    def enqueue(
        self,
        operation_type: OperationType,
        requested_scope: dict[str, Any],
        trigger: str = "manual",
        *,
        in_transaction: bool = False,
    ) -> OperationRunRecord:
        if (
            not isinstance(trigger, str)
            or not trigger.strip()
            or len(trigger) > MAX_OPERATION_TRIGGER_LENGTH
        ):
            raise ValueError("invalid_operation_trigger")
        context = nullcontext() if in_transaction else self._transaction()
        with context:
            record = OperationRunRecord(
                operation_type=operation_type.value,
                trigger=trigger,
                status=OperationStatus.QUEUED.value,
                requested_scope=requested_scope,
                result_summary={},
                attempt_count=0,
                next_attempt_at=func.now(),
            )
            self.session.add(record)
            self.session.flush()
            return record

    def _next_ready_statement(self):
        now = func.now()
        return (
            select(OperationRunRecord)
            .where(
                OperationRunRecord.attempt_count < MAX_ATTEMPTS,
                or_(
                    and_(
                        OperationRunRecord.status == OperationStatus.QUEUED.value,
                        or_(
                            OperationRunRecord.next_attempt_at.is_(None),
                            OperationRunRecord.next_attempt_at <= now,
                        ),
                    ),
                    and_(
                        OperationRunRecord.status == OperationStatus.RUNNING.value,
                        OperationRunRecord.lease_expires_at < now,
                    ),
                ),
            )
            .order_by(OperationRunRecord.created_at, OperationRunRecord.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )

    def lease_next(self, worker_id: str, lease_seconds: float = 60) -> OperationLease | None:
        """Atomically claim the oldest ready row and bind one immutable attempt."""
        with self._transaction():
            operation = self.session.scalar(self._next_ready_statement())
            if operation is None:
                return None
            worker = self._ensure_worker(worker_id)
            if operation.status == OperationStatus.RUNNING.value:
                prior = self.session.scalar(
                    select(OperationAttemptRecord)
                    .where(OperationAttemptRecord.operation_run_id == operation.id)
                    .order_by(OperationAttemptRecord.attempt_number.desc())
                    .limit(1)
                )
                if prior is not None:
                    prior.status = OperationStatus.INTERRUPTED.value
                    prior.finished_at = self._now()
                previous_worker = self.session.get(WorkerRecord, operation.worker_id)
                if previous_worker is not None:
                    previous_worker.status = "stale"
                    previous_worker.current_operation_run_id = None
            operation.attempt_count += 1
            operation.status = OperationStatus.RUNNING.value
            operation.worker_id = worker_id
            operation.heartbeat_at = func.now()
            operation.lease_expires_at = self._lease_expiry(lease_seconds)
            operation.started_at = operation.started_at or func.now()
            operation.updated_at = func.now()
            worker.last_heartbeat_at = self._now()
            worker.status = "running"
            worker.current_operation_run_id = operation.id
            attempt = OperationAttemptRecord(
                operation_run_id=operation.id,
                worker_id=worker_id,
                attempt_number=operation.attempt_count,
                status=OperationStatus.RUNNING.value,
                claimed_at=self._now(),
                heartbeat_at=func.now(),
                lease_expires_at=self._lease_expiry(lease_seconds),
            )
            self.session.add(attempt)
            self.session.flush()
            return OperationLease(
                operation.id,
                attempt.id,
                attempt.attempt_number,
                worker_id,
                operation.requested_scope,
                operation.operation_type,
            )

    def heartbeat_worker(self, worker_id: str, *, status: str = "idle") -> None:
        """Persist liveness even when the durable queue is empty."""
        if status not in {"idle", "running"}:
            raise ValueError("worker status must be idle or running")
        with self._transaction():
            worker = self._ensure_worker(worker_id)
            if worker.current_operation_run_id is not None and status == "idle":
                operation = self.session.get(
                    OperationRunRecord, worker.current_operation_run_id
                )
                if operation is not None and operation.status == OperationStatus.RUNNING.value:
                    return
                worker.current_operation_run_id = None
            worker.last_heartbeat_at = self._now()
            worker.status = status

    def renew_lease(self, lease: OperationLease, lease_seconds: float = 60) -> bool:
        with self._transaction():
            operation, attempt = self._lock_lease_rows(lease)
            if (
                operation is None
                or attempt is None
                or operation.status != OperationStatus.RUNNING.value
                or operation.worker_id != lease.worker_id
            ):
                return False
            operation.heartbeat_at = func.now()
            operation.lease_expires_at = self._lease_expiry(lease_seconds)
            operation.updated_at = func.now()
            attempt.heartbeat_at = func.now()
            attempt.lease_expires_at = self._lease_expiry(lease_seconds)
            worker = self.session.get(WorkerRecord, lease.worker_id)
            if worker is not None:
                worker.last_heartbeat_at = self._now()
                worker.status = "running"
                worker.current_operation_run_id = operation.id
            return True

    def finish_attempt(
        self,
        lease: OperationLease,
        status: OperationStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        result_summary: dict[str, Any] | None = None,
        retryable: bool = True,
        retry_after_seconds: float | None = None,
    ) -> bool:
        with self._transaction():
            operation, attempt = self._lock_lease_rows(lease)
            if (
                operation is None
                or attempt is None
                or operation.status != OperationStatus.RUNNING.value
            ):
                return False
            if (
                operation.worker_id != lease.worker_id
                or attempt.status != OperationStatus.RUNNING.value
            ):
                return False
            final = status
            if operation.cancel_requested_at is not None:
                final = OperationStatus.CANCELLED
            elif (
                status == OperationStatus.FAILED
                and retryable
                and operation.attempt_count < MAX_ATTEMPTS
            ):
                final = OperationStatus.QUEUED
            now = self._now()
            attempt.status = status.value if final == OperationStatus.QUEUED else final.value
            attempt.finished_at = now
            attempt.error_code = error_code
            attempt.error_message = redact(error_message or "") or None
            operation.status = final.value
            operation.error_code = error_code
            operation.error_message = redact(error_message or "") or None
            operation.result_summary = result_summary or operation.result_summary
            operation.lease_expires_at = None
            operation.worker_id = None
            operation.updated_at = func.now()
            worker = self.session.get(WorkerRecord, lease.worker_id)
            if worker is not None:
                worker.last_heartbeat_at = self._now()
                if worker.current_operation_run_id == operation.id:
                    worker.current_operation_run_id = None
                worker.status = "idle"
            if final == OperationStatus.QUEUED:
                operation.next_attempt_at = self._now() + timedelta(
                    seconds=self._retry_delay_seconds(operation.attempt_count, retry_after_seconds)
                )
            else:
                operation.finished_at = now
            self.session.add(
                OperationEventRecord(
                    operation_run_id=operation.id,
                    attempt_id=attempt.id,
                    level="error" if status == OperationStatus.FAILED else "info",
                    phase="finished",
                    message=redact(error_message or final.value),
                    details={},
                    error_code=error_code,
                )
            )
            return True

    def request_cancel(self, operation_id: int) -> bool:
        with self._transaction():
            operation = self.session.get(OperationRunRecord, operation_id, with_for_update=True)
            if operation is None or operation.status in {
                item.value for item in OperationStatus.terminal()
            }:
                return False
            operation.cancel_requested_at = self._now()
            if operation.status == OperationStatus.QUEUED.value:
                operation.status = OperationStatus.CANCELLED.value
                operation.finished_at = self._now()
            operation.updated_at = func.now()
            return True

    def is_cancel_requested(self, lease: OperationLease) -> bool:
        with self._transaction():
            operation = self.session.get(OperationRunRecord, lease.operation_id)
            return operation is None or operation.cancel_requested_at is not None

    def _transaction(self):
        """Finish any implicit read transaction before starting a bounded database operation."""
        if self.session.in_transaction():
            self.session.commit()
        return self.session.begin()

    def _ensure_worker(self, worker_id: str) -> WorkerRecord:
        worker = self.session.get(WorkerRecord, worker_id)
        if worker is None:
            worker = WorkerRecord(
                worker_id=worker_id,
                hostname=worker_id,
                started_at=self._now(),
                last_heartbeat_at=self._now(),
                status="idle",
            )
            self.session.add(worker)
            self.session.flush()
        return worker

    def _lock_lease_rows(
        self, lease: OperationLease
    ) -> tuple[OperationRunRecord | None, OperationAttemptRecord | None]:
        """Lock a lease in the same order used by member-table FK checks.

        High-value wave and catalog member updates validate their attempt foreign
        key before their operation foreign key.  Locking the parent rows in the
        opposite order here creates a PostgreSQL deadlock with concurrent member
        completion, so the attempt row must always be acquired first.
        """
        attempt = self.session.get(
            OperationAttemptRecord, lease.attempt_id, with_for_update=True
        )
        operation = self.session.get(
            OperationRunRecord, lease.operation_id, with_for_update=True
        )
        return operation, attempt

    def _lease_expiry(self, seconds: float):
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            return func.now() + timedelta(seconds=seconds)
        return self._now() + timedelta(seconds=seconds)

    def _retry_delay_seconds(self, attempt_number: int, retry_after_seconds: float | None) -> float:
        """Bound retry pressure while respecting an upstream retry-after hint."""
        exponential = min(2 ** max(attempt_number - 1, 0), 60.0)
        retry_after = min(max(retry_after_seconds or 0.0, 0.0), 300.0)
        base = max(exponential, retry_after)
        jitter = min(max(self._retry_jitter(base), 0.0), base)
        return base + jitter

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)
