"""Worker adapter for bounded event operations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import monotonic

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import EventItemRecord, EventRecord
from newsradar.events.pipeline import EventPipeline
from newsradar.events.repository import EventRepository
from newsradar.events.schema import EventEnrichment, EventStatus, PublishedEvent, ScoreBreakdown
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
            started = monotonic()
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
                    "duplicate_root_suppressed_count": result.duplicate_root_suppressed_count,
                    "model_fallback_count": result.model_fallback_count,
                    "duration_ms": round((monotonic() - started) * 1000, 3),
                    "retry_count": 1 if "retry_of_operation_id" in lease.requested_scope else 0,
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
        claimed: list[int] = []
        try:
            deadline = (
                OperationDeadline.from_scope(lease.requested_scope)
                if "deadline_at" in lease.requested_scope
                else _NoDeadline()
            )
            deadline.check("before_event_action")
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
            invalid_result = _validate_event_action(lease, session, event_id)
            if invalid_result is not None:
                return invalid_result
            repository = EventRepository(session)
            lease_ids = [event_id]
            if lease.operation_type == OperationType.EVENT_MERGE.value:
                lease_ids.append(int(lease.requested_scope["target_event_id"]))
            for claimed_id in sorted(lease_ids):
                deadline.check("before_event_lease")
                if not repository.claim_event(
                    claimed_id, lease.operation_id, datetime.now(UTC) + timedelta(minutes=5)
                ):
                    for release_id in reversed(claimed):
                        repository.release_event(release_id, lease.operation_id)
                    session.commit()
                    return OperationResult(
                        status=OperationStatus.FAILED,
                        error_code="event_lease_unavailable",
                        error_message="Event is being changed by another worker",
                        retryable=True,
                    )
                claimed.append(claimed_id)
            session.commit()
            checkpoint("before_event_action")
            deadline.check("before_event_mutation")
            _apply_event_action(lease, session, event_id)
            deadline.check("after_event_mutation")
            for release_id in reversed(claimed):
                repository.release_event(release_id, lease.operation_id)
            session.commit()
        except OperationTimedOut as error:
            session.rollback()
            for release_id in reversed(claimed):
                EventRepository(session).release_event(release_id, lease.operation_id)
            session.commit()
            return _timeout_result(error)
        except Exception:
            session.rollback()
            # Do not strand a lease when a bounded editorial mutation fails.
            for release_id in reversed(claimed):
                EventRepository(session).release_event(release_id, lease.operation_id)
            session.commit()
            raise
        finally:
            session.close()
        return OperationResult(
            status=OperationStatus.SUCCEEDED,
            result_summary={"event_id": event_id, "action": lease.operation_type},
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


class _NoDeadline:
    def check(self, boundary: str) -> None:
        del boundary


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


def _apply_event_action(lease: OperationLease, session: Session, event_id: int) -> None:
    """Perform only the validated, local mutation; no web process/model work occurs here."""
    action = lease.operation_type
    repository = EventRepository(session)
    if action == OperationType.EVENT_EXCLUDE.value:
        event = session.get(EventRecord, event_id)
        assert event is not None
        repository.publish_complete_event(
            _snapshot(repository, event, status=EventStatus.REJECTED), lease.operation_id
        )
    elif action == OperationType.EVENT_MERGE.value:
        target_id = int(lease.requested_scope["target_event_id"])
        survivor = session.get(EventRecord, event_id)
        target = session.get(EventRecord, target_id)
        assert survivor is not None and target is not None
        rows = session.scalars(
            select(EventItemRecord).where(
                EventItemRecord.event_id == target_id,
                EventItemRecord.removed_version_number.is_(None),
            )
        ).all()
        survivor_ids = _active_ids(session, event_id)
        member_ids = tuple(sorted(survivor_ids | {row.raw_item_id for row in rows}))
        repository.publish_complete_event(
            _snapshot(repository, survivor, source_item_ids=member_ids), lease.operation_id
        )
        repository.publish_complete_event(
            _snapshot(repository, target, status=EventStatus.REJECTED, source_item_ids=()),
            lease.operation_id,
        )
    elif action == OperationType.EVENT_SPLIT.value:
        member_ids = set(lease.requested_scope["member_ids"])
        event = session.get(EventRecord, event_id)
        assert event is not None
        active = _active_ids(session, event_id)
        repository.publish_complete_event(
            _snapshot(repository, event, source_item_ids=tuple(sorted(active - member_ids))),
            lease.operation_id,
        )
        split = PublishedEvent(
            canonical_key=f"{event.canonical_key}:split:{'-'.join(map(str, sorted(member_ids)))}",
            status=EventStatus.DEVELOPING,
            occurred_at=event.occurred_at,
            enrichment=_enrichment(repository, event),
            score=_score(repository, event),
            source_item_ids=tuple(sorted(member_ids)),
        )
        repository.publish_complete_event(split, lease.operation_id)
    elif action in {OperationType.EVENT_RECLUSTER.value, OperationType.EVENT_ENRICH.value}:
        event = session.get(EventRecord, event_id)
        assert event is not None
        enrichment = _enrichment(repository, event)
        if action == OperationType.EVENT_ENRICH.value:
            enrichment = enrichment.model_copy(update={"origin": "rule_fallback", "confidence": 0})
        repository.publish_complete_event(
            _snapshot(repository, event, enrichment=enrichment), lease.operation_id
        )


def _active_ids(session: Session, event_id: int) -> set[int]:
    statement = select(EventItemRecord.raw_item_id).where(
        EventItemRecord.event_id == event_id,
        EventItemRecord.removed_version_number.is_(None),
    )
    return set(session.scalars(statement))


def _score(repository: EventRepository, event: EventRecord) -> ScoreBreakdown:
    current = repository.get_current_event(event.id)
    if current and current.payload.get("score"):
        return ScoreBreakdown.model_validate(current.payload["score"])
    return ScoreBreakdown(
        ai_relevance=0, source_coverage=0, source_authority=0, recency=0,
        engagement_velocity=0, novelty=0, importance=0, credibility=0, heat=0,
        rule_version="manual-v1", reasons=("manual_event_action",),
    )


def _enrichment(repository: EventRepository, event: EventRecord) -> EventEnrichment:
    current = repository.get_current_event(event.id)
    if current and current.payload.get("enrichment"):
        return EventEnrichment.model_validate(current.payload["enrichment"])
    return EventEnrichment(
        zh_title=event.canonical_key, zh_summary=event.canonical_key,
        why_it_matters="人工操作保留可追溯事件版本。", origin="rule_fallback", confidence=0,
    )


def _snapshot(
    repository: EventRepository, event: EventRecord, *, status: EventStatus | None = None,
    source_item_ids: tuple[int, ...] | None = None, enrichment: EventEnrichment | None = None,
) -> PublishedEvent:
    current = repository.get_current_event(event.id)
    evidence = ()
    category = None
    occurred_at = event.occurred_at
    if current:
        payload = current.payload
        evidence = tuple(payload.get("evidence", ()))
        category = payload.get("category")
        occurred_at = payload.get("occurred_at") or occurred_at
    members = source_item_ids
    if members is None:
        members = tuple(sorted(_active_ids(repository.session, event.id)))
    return PublishedEvent(
        event_id=event.id, canonical_key=event.canonical_key,
        status=status or EventStatus(event.status), category=category, occurred_at=occurred_at,
        enrichment=enrichment or _enrichment(repository, event), score=_score(repository, event),
        evidence=evidence,
        source_item_ids=members,
    )
