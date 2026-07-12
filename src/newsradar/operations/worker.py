from __future__ import annotations

from collections.abc import Callable

from newsradar.operations.repository import OperationLease, OperationRepository
from newsradar.operations.schema import OperationStatus
from newsradar.operations.service import OperationService

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
    ):
        self.repository = repository
        self.worker_id = worker_id
        self._heartbeat = heartbeat or (lambda lease: self.repository.renew_lease(lease))

    def run_once(self, handler: Handler) -> bool:
        lease = self.repository.lease_next(self.worker_id)
        if lease is None:
            return False
        service = OperationService(self.repository, self._heartbeat)

        def checkpoint(boundary: str) -> None:
            if not service.checkpoint(lease, boundary):
                raise _Cancelled()

        try:
            handler(lease, checkpoint)  # deliberately outside the lease transaction
        except _Cancelled:
            self.repository.finish_attempt(lease, OperationStatus.CANCELLED)
            return False
        except Exception as error:
            self.repository.finish_attempt(
                lease, OperationStatus.FAILED, error_code="internal", error_message=str(error)
            )
            return False
        self.repository.finish_attempt(lease, OperationStatus.SUCCEEDED)
        return True
