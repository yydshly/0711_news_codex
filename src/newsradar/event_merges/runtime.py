"""Worker adapter for bounded, local-only event merge scans."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session

from newsradar.event_merges.facts import EVENT_MERGE_RULE_VERSION
from newsradar.event_merges.service import EventMergeService
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS
from newsradar.operations.deadlines import OperationDeadline, OperationTimedOut
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.operations.worker import OperationCancelled, OperationResult


class EventMergeOperationHandler:
    def __init__(self, session_factory: Callable[[], Session | None]) -> None:
        self._session_factory = session_factory

    @classmethod
    def production(
        cls, session_factory: Callable[[], Session]
    ) -> EventMergeOperationHandler:
        return cls(session_factory)

    def __call__(
        self, lease: OperationLease, checkpoint: Callable[[str], None]
    ) -> OperationResult:
        if (
            lease.operation_type != OperationType.EVENT_MERGE_SCAN.value
            or not _valid_scope(lease.requested_scope)
        ):
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="invalid_event_merge_scan_scope",
                retryable=False,
            )
        try:
            deadline = OperationDeadline.from_scope(lease.requested_scope)
            deadline.check("before_event_merge_scan")
        except (OperationTimedOut, ValueError) as error:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="operation_timeout",
                error_message=str(error),
                retryable=False,
            )
        try:
            session = self._session_factory()
        except Exception:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="event_merge_runtime_unavailable",
                error_message="Event merge database session is unavailable",
                retryable=True,
            )
        if session is None:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="event_merge_runtime_unavailable",
                retryable=True,
            )

        def guarded_checkpoint(boundary: str) -> None:
            checkpoint(boundary)
            deadline.check(boundary)

        try:
            result = EventMergeService(session).scan(
                lease.operation_id, guarded_checkpoint
            )
        except OperationTimedOut as error:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="operation_timeout",
                error_message=str(error),
                retryable=False,
            )
        except OperationCancelled:
            raise
        except Exception:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="event_merge_scan_failed",
                error_message="Event merge scan failed",
                retryable=True,
            )
        finally:
            session.close()
        return OperationResult(
            status=(
                OperationStatus.PARTIAL
                if result.failure_reasons
                else OperationStatus.SUCCEEDED
            ),
            result_summary=result.as_dict(),
            retryable=False,
        )


def _valid_scope(scope: dict[str, object]) -> bool:
    actor = scope.get("actor")
    window_end = scope.get("window_end")
    deadline_at = scope.get("deadline_at")
    identity = scope.get("idempotency_key")
    if (
        not isinstance(actor, str)
        or not 0 < len(actor) <= 120
        or scope.get("algorithm_version") != EVENT_MERGE_RULE_VERSION
        or scope.get("algorithm_versions") != dict(EVENT_ALGORITHM_VERSIONS)
        or not isinstance(window_end, str)
        or not 0 < len(window_end) <= 64
        or not isinstance(identity, str)
        or not identity.startswith("event-merge-scan:")
        or len(identity) > 128
        or not isinstance(deadline_at, str)
        or not 0 < len(deadline_at) <= 64
    ):
        return False
    try:
        parsed = datetime.fromisoformat(window_end.replace("Z", "+00:00"))
        deadline = datetime.fromisoformat(deadline_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and deadline.tzinfo is not None
