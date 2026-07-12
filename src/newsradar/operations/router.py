"""Dispatch durable operation leases to their registered worker handlers."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus
from newsradar.operations.worker import Handler, OperationResult


class OperationRouter:
    """The single Worker handler for all durable operation types."""

    def __init__(self, handlers: Mapping[str, Handler] | None = None) -> None:
        self._handlers = dict(handlers or {})

    def register(self, operation_type: str, handler: Handler) -> None:
        self._handlers[operation_type] = handler

    def __call__(
        self, lease: OperationLease, checkpoint: Callable[[str], None]
    ) -> OperationResult | None:
        handler = self._handlers.get(lease.operation_type)
        if handler is None:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="unsupported_operation_type",
                error_message=f"No worker handler is registered for {lease.operation_type}",
                retryable=False,
            )
        return handler(lease, checkpoint)
