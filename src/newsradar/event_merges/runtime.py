"""Worker adapter for candidate scans and revalidated merge decisions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session

from newsradar.event_merges.facts import EVENT_MERGE_RULE_VERSION
from newsradar.event_merges.service import EventMergeLeaseUnavailable, EventMergeService
from newsradar.events.quality import QualityInputUnavailable
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
        if lease.operation_type == OperationType.EVENT_MERGE_SCAN.value:
            if not _valid_scope(lease.requested_scope):
                return OperationResult(
                    status=OperationStatus.FAILED,
                    error_code="invalid_event_merge_scan_scope",
                    retryable=False,
                )
            return self._run_scan(lease, checkpoint)
        if lease.operation_type == OperationType.EVENT_MERGE.value:
            if not _valid_decision_scope(lease.requested_scope):
                return OperationResult(
                    status=OperationStatus.FAILED,
                    error_code="event_merge_candidate_required",
                    retryable=False,
                )
            return self._run_decision(lease, checkpoint)
        return OperationResult(
            status=OperationStatus.FAILED,
            error_code="unsupported_operation_type",
            retryable=False,
        )

    def _run_scan(
        self, lease: OperationLease, checkpoint: Callable[[str], None]
    ) -> OperationResult:
        deadline_result = _deadline(lease, "before_event_merge_scan")
        if isinstance(deadline_result, OperationResult):
            return deadline_result
        deadline = deadline_result
        session = self._open_session()
        if isinstance(session, OperationResult):
            return session

        def guarded_checkpoint(boundary: str) -> None:
            checkpoint(boundary)
            deadline.check(boundary)

        try:
            result = EventMergeService(session).scan(
                lease.operation_id, guarded_checkpoint
            )
        except OperationTimedOut as error:
            return _timeout_result(error)
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

    def _run_decision(
        self, lease: OperationLease, checkpoint: Callable[[str], None]
    ) -> OperationResult:
        deadline_result = _deadline(lease, "before_event_merge_decision")
        if isinstance(deadline_result, OperationResult):
            return deadline_result
        deadline = deadline_result
        session = self._open_session()
        if isinstance(session, OperationResult):
            return session

        def guarded_checkpoint(boundary: str) -> None:
            checkpoint(boundary)
            deadline.check(boundary)

        candidate_id = int(lease.requested_scope["candidate_id"])
        decision = str(lease.requested_scope["decision"])
        try:
            guarded_checkpoint("before_event_merge_decision_mutation")
            service = EventMergeService(session)
            if decision in {"confirm", "dismiss", "recheck"}:
                reviewed = service.review(
                    candidate_id, decision, lease.operation_id
                )
                if decision in {"dismiss", "recheck"}:
                    return OperationResult(
                        status=OperationStatus.SUCCEEDED,
                        result_summary={
                            "candidate_id": reviewed.id,
                            "status": str(reviewed.status),
                        },
                        retryable=False,
                    )
            result = service.apply(
                candidate_id,
                lease.operation_id,
                guarded_checkpoint,
            )
            if result.status == "expired":
                return OperationResult(
                    status=OperationStatus.FAILED,
                    error_code=result.error_code,
                    result_summary=result.model_dump(mode="json"),
                    retryable=False,
                )
            return OperationResult(
                status=OperationStatus.SUCCEEDED,
                result_summary=result.model_dump(mode="json"),
                retryable=False,
            )
        except OperationTimedOut as error:
            return _timeout_result(error)
        except OperationCancelled:
            raise
        except EventMergeLeaseUnavailable as error:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code=error.error_code,
                error_message=str(error),
                retryable=True,
            )
        except QualityInputUnavailable as error:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="event_quality_input_unavailable",
                error_message=str(error),
                retryable=False,
            )
        except (LookupError, ValueError) as error:
            code = str(error).split(":", 1)[0]
            if not code.startswith("event_merge_"):
                code = "event_merge_invalid_decision"
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code=code,
                retryable=False,
            )
        except Exception:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="event_merge_apply_failed",
                error_message="Event merge application failed",
                retryable=True,
            )
        finally:
            session.close()

    def _open_session(self) -> Session | OperationResult:
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
        return session


def _deadline(
    lease: OperationLease, boundary: str
) -> OperationDeadline | OperationResult:
    try:
        deadline = OperationDeadline.from_scope(lease.requested_scope)
        deadline.check(boundary)
        return deadline
    except (OperationTimedOut, ValueError) as error:
        return _timeout_result(error)


def _timeout_result(error: Exception) -> OperationResult:
    return OperationResult(
        status=OperationStatus.FAILED,
        error_code="operation_timeout",
        error_message=str(error),
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


def _valid_decision_scope(scope: dict[str, object]) -> bool:
    candidate_id = scope.get("candidate_id")
    decision = scope.get("decision")
    actor = scope.get("actor")
    identity = scope.get("idempotency_key")
    deadline_at = scope.get("deadline_at")
    if (
        isinstance(candidate_id, bool)
        or not isinstance(candidate_id, int)
        or candidate_id <= 0
        or decision not in {"apply", "confirm", "dismiss", "recheck"}
        or not isinstance(actor, str)
        or not 0 < len(actor) <= 120
        or not isinstance(identity, str)
        or not identity.startswith(f"event-merge-decision:{decision}:{candidate_id}:")
        or len(identity) > 256
        or not isinstance(deadline_at, str)
        or not 0 < len(deadline_at) <= 64
        or "event_id" in scope
        or "target_event_id" in scope
    ):
        return False
    try:
        deadline = datetime.fromisoformat(deadline_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return deadline.tzinfo is not None
