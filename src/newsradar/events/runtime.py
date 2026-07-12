"""Worker adapter for bounded event operations."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import EventItemRecord, EventRecord
from newsradar.events.pipeline import EventPipeline
from newsradar.operations.deadlines import OperationDeadline, OperationTimedOut
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.operations.worker import OperationResult


class EventOperationHandler:
    """Execute event work only after a Worker has claimed its durable lease."""

    def __init__(self, session_factory: Callable[[], Session | None]) -> None:
        self._session_factory = session_factory

    @classmethod
    def production(cls, session_factory: Callable[[], Session]) -> EventOperationHandler:
        return cls(session_factory)

    def __call__(self, lease: OperationLease, checkpoint: Callable[[str], None]) -> OperationResult:
        if lease.operation_type not in {item.value for item in _EVENT_TYPES}:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="unsupported_operation_type",
                retryable=False,
            )
        if lease.operation_type == OperationType.EVENT_PIPELINE.value:
            hours = lease.requested_scope.get("window_hours")
            if not isinstance(hours, int) or hours <= 0:
                return OperationResult(
                    status=OperationStatus.FAILED,
                    error_code="invalid_event_scope",
                    error_message="Event pipeline operations require a positive window_hours",
                    retryable=False,
                )
            try:
                deadline = OperationDeadline.from_scope(lease.requested_scope)
                deadline.check("before_event_pipeline")
            except (OperationTimedOut, ValueError) as error:
                return _timeout_result(error)
            session = self._session_factory()
            if session is None:
                return OperationResult(
                    status=OperationStatus.FAILED,
                    error_code="event_runtime_unavailable",
                    retryable=True,
                )
            try:
                result = EventPipeline.production(session).run(
                    window_hours=hours,
                    operation_id=lease.operation_id,
                    checkpoint=_deadline_checkpoint(checkpoint, deadline),
                )
            except OperationTimedOut as error:
                return _timeout_result(error)
            finally:
                session.close()
            return OperationResult(
                result_summary={
                    "event_ids": list(result.current_event_ids),
                    "created_event_versions": result.created_event_versions,
                    "candidate_count": result.candidate_count,
                    "processed_item_count": result.processed_item_count,
                }
            )
        event_id = lease.requested_scope.get("event_id")
        if not isinstance(event_id, int) or event_id <= 0:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="invalid_event_scope",
                error_message="Event actions require an event_id",
                retryable=False,
            )
        session = self._session_factory()
        if session is None:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="event_runtime_unavailable",
                retryable=True,
            )
        try:
            invalid_result = _validate_event_action(lease, session, event_id)
        finally:
            session.close()
        if invalid_result is not None:
            return invalid_result
        checkpoint("before_event_action")
        return OperationResult(
            status=OperationStatus.FAILED,
            error_code="unsupported_action",
            error_message=(
                f"{lease.operation_type} is queued safely but has no worker mutation implementation"
            ),
            result_summary={"event_id": event_id, "action": lease.operation_type},
            retryable=False,
        )


_EVENT_TYPES = frozenset(
    {
        OperationType.EVENT_PIPELINE,
        OperationType.EVENT_RECLUSTER,
        OperationType.EVENT_ENRICH,
        OperationType.EVENT_MERGE,
        OperationType.EVENT_SPLIT,
        OperationType.EVENT_EXCLUDE,
    }
)


def _deadline_checkpoint(
    checkpoint: Callable[[str], None], deadline: OperationDeadline
) -> Callable[[str], None]:
    def check(boundary: str) -> None:
        checkpoint(boundary)
        deadline.check(boundary)

    return check


def _timeout_result(error: Exception) -> OperationResult:
    return OperationResult(
        status=OperationStatus.FAILED,
        error_code="operation_timeout",
        error_message=str(error),
        retryable=False,
    )


def _validate_event_action(
    lease: OperationLease, session: Session, event_id: int
) -> OperationResult | None:
    scope = lease.requested_scope
    if session.get(EventRecord, event_id) is None:
        return _unknown_event(event_id)
    if scope.get("actor") != "web":
        return _invalid_scope("Event actions require actor=web")
    action = lease.operation_type
    if action == OperationType.EVENT_MERGE.value:
        target_event_id = scope.get("target_event_id")
        if (
            not isinstance(target_event_id, int)
            or target_event_id <= 0
            or target_event_id == event_id
        ):
            return _invalid_scope("Merge requires a distinct positive target_event_id")
        if session.get(EventRecord, target_event_id) is None:
            return _unknown_event(target_event_id)
    elif action == OperationType.EVENT_SPLIT.value:
        member_ids = scope.get("member_ids")
        if (
            not isinstance(member_ids, list)
            or not member_ids
            or any(not isinstance(item, int) or item <= 0 for item in member_ids)
        ):
            return _invalid_scope("Split requires non-empty positive member_ids")
        active_ids = set(
            session.scalars(
                select(EventItemRecord.raw_item_id).where(
                    EventItemRecord.event_id == event_id,
                    EventItemRecord.removed_version_number.is_(None),
                )
            )
        )
        if not set(member_ids).issubset(active_ids):
            return _invalid_scope("Split members must be active event memberships")
    elif action not in {
        OperationType.EVENT_RECLUSTER.value,
        OperationType.EVENT_ENRICH.value,
        OperationType.EVENT_EXCLUDE.value,
    }:
        return _invalid_scope("Unknown event action")
    return None


def _invalid_scope(message: str) -> OperationResult:
    return OperationResult(
        status=OperationStatus.FAILED,
        error_code="invalid_event_scope",
        error_message=message,
        retryable=False,
    )


def _unknown_event(event_id: int) -> OperationResult:
    return OperationResult(
        status=OperationStatus.FAILED,
        error_code="unknown_event",
        error_message=f"Event {event_id} does not exist",
        retryable=False,
    )
