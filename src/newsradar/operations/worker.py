from __future__ import annotations

import logging
from collections.abc import Callable
from time import monotonic

from newsradar.operations.repository import OperationLease, OperationRepository
from newsradar.operations.schema import OperationStatus

Handler = Callable[[OperationLease, Callable[[str], None]], None]


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
        logger: logging.Logger | None = None,
    ):
        self.repository = repository
        self.worker_id = worker_id
        self._heartbeat = heartbeat or (lambda lease: self.repository.renew_lease(lease))
        self._clock = clock
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._logger = logger or logging.getLogger("newsradar")

    def run_once(self, handler: Handler) -> bool:
        lease = self.repository.lease_next(self.worker_id)
        if lease is None:
            return False
        last_heartbeat = self._clock()

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
            if self.repository.is_cancel_requested(lease):
                raise _Cancelled()
            now = self._clock()
            if now - last_heartbeat >= self._heartbeat_interval_seconds:
                self._heartbeat(lease)
                last_heartbeat = now

        try:
            log("operation_started")
            handler(lease, checkpoint)  # deliberately outside the lease transaction
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
        self.repository.finish_attempt(lease, OperationStatus.SUCCEEDED)
        log("operation_succeeded")
        return True
