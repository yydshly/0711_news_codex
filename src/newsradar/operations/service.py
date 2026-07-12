from __future__ import annotations

from collections.abc import Callable

from newsradar.operations.repository import OperationLease, OperationRepository


class OperationService:
    """Small worker-facing facade that keeps lease checks explicit at work boundaries."""

    def __init__(
        self, repository: OperationRepository, heartbeat: Callable[[OperationLease], None]
    ):
        self.repository = repository
        self.heartbeat = heartbeat

    def checkpoint(self, lease: OperationLease, _boundary: str) -> bool:
        if self.repository.is_cancel_requested(lease):
            return False
        self.heartbeat(lease)
        return True
