from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event, Thread
from time import monotonic
from typing import Any

from newsradar.operations.repository import OperationLease, OperationRepository
from newsradar.operations.schema import OperationStatus


@dataclass(frozen=True)
class OperationResult:
    """A handler outcome that maps domain work to a durable operation state."""

    status: OperationStatus = OperationStatus.SUCCEEDED
    error_code: str | None = None
    error_message: str | None = None
    result_summary: dict[str, Any] = field(default_factory=dict)
    retryable: bool = True
    retry_after_seconds: float | None = None


Handler = Callable[[OperationLease, Callable[[str], None]], OperationResult | None]
LeaseGuard = Callable[[OperationLease], bool]


class _Cancelled(Exception):
    pass


class Worker:
    """Lease one operation, execute external work, then persist its outcome."""

    def __init__(
        self,
        repository: OperationRepository,
        worker_id: str,
        *,
        heartbeat: Callable[[OperationLease], None] | None = None,
        clock: Callable[[], float] = monotonic,
        heartbeat_interval_seconds: float = 0,
        lease_seconds: float = 60,
        lease_guard: LeaseGuard | None = None,
        monitor_interval_seconds: float = 0,
        logger: logging.Logger | None = None,
    ):
        self.repository = repository
        self.worker_id = worker_id
        self._heartbeat = heartbeat or (lambda lease: self.repository.renew_lease(lease))
        self._clock = clock
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._lease_seconds = lease_seconds
        self._lease_guard = lease_guard
        self._monitor_interval_seconds = monitor_interval_seconds
        self._logger = logger or logging.getLogger("newsradar")

    def run_once(self, handler: Handler) -> bool:
        lease = self.repository.lease_next(self.worker_id, lease_seconds=self._lease_seconds)
        if lease is None:
            return False
        last_heartbeat = self._clock()
        cancellation_seen = Event()

        def log(message: str) -> None:
            scope = lease.requested_scope
            self._logger.info(
                message,
                extra={
                    "correlation_id": f"operation:{lease.operation_id}:attempt:{lease.attempt_id}",
                    "operation_id": lease.operation_id,
                    "attempt_id": lease.attempt_id,
                    "worker_id": lease.worker_id,
                    "source_id": scope.get("source_id"),
                    "request_id": scope.get("request_id"),
                },
            )

        def checkpoint(boundary: str) -> None:
            nonlocal last_heartbeat
            if cancellation_seen.is_set() or (
                self._lease_guard is not None and not self._lease_guard(lease)
            ) or (
                self._lease_guard is None and self.repository.is_cancel_requested(lease)
            ):
                raise _Cancelled()
            now = self._clock()
            if (
                self._lease_guard is None
                and now - last_heartbeat >= self._heartbeat_interval_seconds
            ):
                self._heartbeat(lease)
                last_heartbeat = now

        try:
            log("operation_started")
            result = self._run_handler_with_monitor(
                handler, lease, checkpoint, cancellation_seen
            )  # deliberately outside the lease transaction
        except _Cancelled:
            self.repository.finish_attempt(lease, OperationStatus.CANCELLED)
            log("operation_cancelled")
            return False
        except Exception as error:
            self.repository.finish_attempt(
                lease, OperationStatus.FAILED, error_code="internal", error_message=str(error)
            )
            log("operation_failed")
            return False
        # Older handlers are side-effect only.  Treat their return value as success
        # until they opt into the structured domain outcome contract.
        result = result if isinstance(result, OperationResult) else OperationResult()
        self.repository.finish_attempt(
            lease,
            result.status,
            error_code=result.error_code,
            error_message=result.error_message,
            result_summary=result.result_summary,
            retryable=result.retryable,
            retry_after_seconds=result.retry_after_seconds,
        )
        log(f"operation_{result.status.value}")
        return result.status in {OperationStatus.SUCCEEDED, OperationStatus.PARTIAL}

    def _run_handler_with_monitor(
        self,
        handler: Handler,
        lease: OperationLease,
        checkpoint: Callable[[str], None],
        cancellation_seen: Event,
    ) -> OperationResult | None:
        """Keep a production lease alive while uninterruptible network I/O is in flight."""
        if self._lease_guard is None or self._monitor_interval_seconds <= 0:
            return handler(lease, checkpoint)
        completed, result_box = Event(), []
        error_box: list[Exception] = []

        def invoke() -> None:
            try:
                result_box.append(handler(lease, checkpoint))
            except Exception as error:
                error_box.append(error)
            finally:
                completed.set()

        thread = Thread(
            target=invoke, name=f"newsradar-operation-{lease.operation_id}", daemon=True
        )
        thread.start()
        while not completed.wait(self._monitor_interval_seconds):
            if not self._lease_guard(lease):
                cancellation_seen.set()
        thread.join()
        if error_box:
            raise error_box[0]
        return result_box[0] if result_box else None
