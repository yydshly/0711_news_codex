from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from json import dumps
from time import monotonic, sleep

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from newsradar.db.models import (
    OperationRunRecord,
    SourceRemediationBatchRecord,
    SourceRemediationMemberRecord,
)
from newsradar.operations.repository import OperationRepository
from newsradar.operations.retry_policy import is_retryable_error
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.remediation.evidence_links import is_valid_remediation_content_link
from newsradar.settings import Settings, get_settings


class OperationCommandService:
    """Shared Web and CLI command boundary for durable operations."""

    def __init__(
        self,
        session: Session,
        *,
        sleeper: Callable[[float], None] = sleep,
        clock: Callable[[], float] = monotonic,
        utcnow: Callable[[], datetime] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self._sleeper = sleeper
        self._clock = clock
        self._utcnow = utcnow or (lambda: datetime.now(UTC))
        self._settings = settings or get_settings()

    def enqueue_fetch(
        self,
        *,
        source_id: str,
        provider: str | None = None,
        dry_run: bool = False,
        max_items: int | None = None,
        one_off: bool = False,
        trial: bool = False,
        remediation_content_probe_id: int | None = None,
        trigger: str,
    ) -> int:
        if remediation_content_probe_id is not None:
            if not trial:
                raise ValueError("remediation_content_link_requires_trial")
            if not is_valid_remediation_content_link(
                self.session,
                source_id=source_id,
                content_probe_id=remediation_content_probe_id,
            ):
                raise ValueError("invalid_remediation_content_link")
        deadline_at = self._utcnow() + timedelta(seconds=self._settings.operation_timeout_seconds)
        record = OperationRepository(self.session).enqueue(
            OperationType.FETCH,
            {
                "source_id": source_id,
                "provider": provider,
                "dry_run": dry_run,
                "max_items": max_items,
                "one_off": one_off,
                "trial": trial,
                **(
                    {"remediation_content_probe_id": remediation_content_probe_id}
                    if remediation_content_probe_id is not None
                    else {}
                ),
                "deadline_at": deadline_at.isoformat(),
            },
            trigger=trigger,
        )
        self.session.commit()
        return record.id

    def enqueue_source_remediation(
        self,
        *,
        source_id: str,
        candidate_key: str,
        original_probe_id: int,
        baseline_at: datetime,
        trigger: str,
        retry_of_operation_id: int | None = None,
    ) -> int:
        if not source_id or not candidate_key or original_probe_id <= 0:
            raise ValueError("invalid_source_remediation_scope")
        member = self.session.scalar(
            select(SourceRemediationMemberRecord)
            .join(
                SourceRemediationBatchRecord,
                SourceRemediationBatchRecord.id == SourceRemediationMemberRecord.batch_id,
            )
            .where(
                SourceRemediationBatchRecord.baseline_at == baseline_at,
                SourceRemediationMemberRecord.source_id == source_id,
                SourceRemediationMemberRecord.original_probe_id == original_probe_id,
            )
        )
        if member is None:
            raise ValueError("source_not_in_frozen_remediation_batch")
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            self.session.execute(
                text(
                    "SELECT pg_advisory_xact_lock(hashtext('newsradar:source-remediation-enqueue'))"
                )
            )
        active = self.session.scalar(
            select(OperationRunRecord.id).where(
                OperationRunRecord.operation_type == OperationType.SOURCE_REMEDIATION.value,
                OperationRunRecord.status.in_(
                    [OperationStatus.QUEUED.value, OperationStatus.RUNNING.value]
                ),
            )
        )
        if active is not None:
            raise ValueError("active_source_remediation_exists")
        now = self._utcnow()
        record = OperationRepository(self.session).enqueue(
            OperationType.SOURCE_REMEDIATION,
            {
                "source_id": source_id,
                "candidate_key": candidate_key,
                "original_probe_id": original_probe_id,
                "baseline_at": baseline_at.isoformat(),
                "deadline_at": (
                    now + timedelta(seconds=self._settings.operation_timeout_seconds)
                ).isoformat(),
                **(
                    {"retry_of_operation_id": retry_of_operation_id}
                    if retry_of_operation_id is not None
                    else {}
                ),
            },
            trigger=trigger,
        )
        self.session.commit()
        return record.id

    def retry_source_remediation(self, operation_id: int, *, trigger: str) -> int:
        """Permit one deliberately requested retry, only for transport failures."""
        original = self.session.get(OperationRunRecord, operation_id)
        terminal_statuses = {item.value for item in OperationStatus.terminal()}
        category = (
            original.result_summary.get("category")
            if original is not None and isinstance(original.result_summary, dict)
            else None
        )
        existing_retry = any(
            record.requested_scope.get("retry_of_operation_id") == operation_id
            for record in self.session.scalars(
                select(OperationRunRecord).where(
                    OperationRunRecord.operation_type == OperationType.SOURCE_REMEDIATION.value
                )
            )
        )
        if (
            original is None
            or original.operation_type != OperationType.SOURCE_REMEDIATION.value
            or original.status not in terminal_statuses
            or category != "network_transient"
            or existing_retry
        ):
            raise ValueError("source_remediation_retry_not_allowed")
        scope = original.requested_scope
        return self.enqueue_source_remediation(
            source_id=str(scope.get("source_id", "")),
            candidate_key=str(scope.get("candidate_key", "")),
            original_probe_id=int(scope.get("original_probe_id", 0)),
            baseline_at=datetime.fromisoformat(str(scope.get("baseline_at"))),
            trigger=trigger,
            retry_of_operation_id=operation_id,
        )

    def enqueue_event_pipeline(self, *, window_hours: int, trigger: str) -> int:
        if window_hours <= 0:
            raise ValueError("window_hours must be positive")
        now = self._utcnow()
        versions = {"relevance": "relevance-v1", "entities": "entities-v1", "cluster": "cluster-v1"}
        window_end = now.replace(minute=0, second=0, microsecond=0)
        key_parts = {
            "window_end": window_end.isoformat(),
            "window_hours": window_hours,
            "versions": versions,
        }
        scope = {
            "actor": trigger,
            "window_hours": window_hours,
            "algorithm_versions": versions,
            "window_end": window_end.isoformat(),
            "idempotency_key": "event-pipeline:"
            + sha256(dumps(key_parts, sort_keys=True).encode()).hexdigest(),
            "deadline_at": (
                now + timedelta(seconds=self._settings.operation_timeout_seconds)
            ).isoformat(),
        }
        record = OperationRepository(self.session).enqueue(
            OperationType.EVENT_PIPELINE, scope, trigger=trigger
        )
        self.session.commit()
        return record.id

    def enqueue_event_action(
        self, action: str, event_id: int, payload: dict | None, trigger: str
    ) -> int:
        operation_type = {
            "recluster": OperationType.EVENT_RECLUSTER,
            "enrich": OperationType.EVENT_ENRICH,
            "merge": OperationType.EVENT_MERGE,
            "split": OperationType.EVENT_SPLIT,
            "exclude": OperationType.EVENT_EXCLUDE,
        }.get(action)
        if operation_type is None or event_id <= 0:
            raise ValueError("invalid event action")
        now = self._utcnow()
        payload_data = payload or {}
        scope = {
            "event_id": event_id,
            "payload": payload_data,
            **{key: value for key, value in payload_data.items() if key != "actor"},
            "actor": trigger,
            "idempotency_key": f"event-action:{action}:{event_id}:"
            + sha256(dumps(payload_data, sort_keys=True).encode()).hexdigest(),
            "deadline_at": (
                now + timedelta(seconds=self._settings.operation_timeout_seconds)
            ).isoformat(),
        }
        record = OperationRepository(self.session).enqueue(operation_type, scope, trigger=trigger)
        self.session.commit()
        return record.id

    def retry(self, operation_id: int, *, trigger: str) -> int:
        original = self.session.get(OperationRunRecord, operation_id)
        terminal_statuses = {item.value for item in OperationStatus.terminal()}
        if (
            original is None
            or original.status not in terminal_statuses
            or original.operation_type == OperationType.SOURCE_REMEDIATION.value
            or not is_retryable_error(original.error_code)
        ):
            raise ValueError("operation is not retryable")
        scope = dict(original.requested_scope)
        scope["retry_of_operation_id"] = operation_id
        scope["deadline_at"] = (
            self._utcnow() + timedelta(seconds=self._settings.operation_timeout_seconds)
        ).isoformat()
        record = OperationRepository(self.session).enqueue(
            OperationType(original.operation_type), scope, trigger=trigger
        )
        self.session.commit()
        return record.id

    def cancel(self, operation_id: int) -> bool:
        result = OperationRepository(self.session).request_cancel(operation_id)
        self.session.commit()
        return result

    def wait_for_terminal(
        self, operation_id: int, *, timeout_seconds: float = 1800, poll_seconds: float = 0.25
    ) -> OperationRunRecord:
        deadline = self._clock() + timeout_seconds
        terminal_statuses = {item.value for item in OperationStatus.terminal()}
        while self._clock() < deadline:
            self.session.expire_all()
            record = self.session.get(OperationRunRecord, operation_id)
            if record is None:
                raise LookupError(operation_id)
            if record.status in terminal_statuses:
                return record
            self._sleeper(poll_seconds)
        raise TimeoutError(f"operation {operation_id} did not finish within {timeout_seconds}s")
