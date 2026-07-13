from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from typing import Protocol

from newsradar.db.session import create_session
from newsradar.ingestion.fetchers.base import FetcherFactory, HttpPolicy
from newsradar.ingestion.schema import FetchOutcome, FetchResult
from newsradar.ingestion.service import IngestionService, SourceFetchSummary
from newsradar.ingestion.trial import evaluate_trial_eligibility
from newsradar.operations.deadlines import OperationDeadline, OperationTimedOut
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import ErrorCategory, OperationStatus, OperationType
from newsradar.operations.worker import OperationResult
from newsradar.sources.schema import SourceDefinition
from newsradar.sources.repository import SourceRepository


class FetchExecutor(Protocol):
    def __call__(
        self,
        source: SourceDefinition,
        operation_id: int,
        checkpoint: Callable[[str], None],
        requested_scope: Mapping[str, object],
    ) -> SourceFetchSummary: ...


class FetchOperationHandler:
    """Execute one approved source fetch after a durable worker lease is claimed."""

    def __init__(self, sources: Iterable[SourceDefinition], executor: FetchExecutor):
        self._sources = {source.id: source for source in sources}
        self._executor = executor

    @classmethod
    def production(cls, sources: Iterable[SourceDefinition]) -> FetchOperationHandler:
        return cls(sources, _execute_production_fetch)

    def __call__(
        self, lease: OperationLease, checkpoint: Callable[[str], None]
    ) -> OperationResult:
        if lease.operation_type != OperationType.FETCH.value:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="unsupported_operation_type",
                error_message=f"No worker handler is registered for {lease.operation_type}",
                retryable=False,
            )
        source_id = lease.requested_scope.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="invalid_fetch_scope",
                error_message="Fetch operations require a source_id",
                retryable=False,
            )
        source = self._sources.get(source_id)
        if source is None:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="unknown_source",
                error_message=(
                    "The queued source is no longer present in the audited source catalog"
                ),
                retryable=False,
            )
        deadline = None
        if "deadline_at" in lease.requested_scope:
            try:
                deadline = OperationDeadline.from_scope(lease.requested_scope)
                deadline.check("before_source")
            except (OperationTimedOut, ValueError) as error:
                return OperationResult(
                    status=OperationStatus.FAILED,
                    error_code="operation_timeout",
                    error_message=str(error),
                    retryable=False,
                )
        checkpoint("before_source")
        summary = self._executor(
            source,
            lease.operation_id,
            checkpoint,
            lease.requested_scope,
        )
        checkpoint("after_source")
        if deadline is not None:
            try:
                deadline.check("after_source")
            except OperationTimedOut as error:
                return OperationResult(
                    status=OperationStatus.FAILED,
                    error_code="operation_timeout",
                    error_message=str(error),
                    retryable=False,
                )
        return _result_from_summary(summary)


def _result_from_summary(summary: SourceFetchSummary) -> OperationResult:
    result = summary.result
    summary_data = {
        "source_id": summary.source_id,
        "fetch_run_id": summary.fetch_run_id,
        "outcome": result.outcome.value,
        "items_received": result.items_received,
        "items_inserted": result.items_inserted,
    }
    if result.outcome == FetchOutcome.SUCCEEDED:
        return OperationResult(result_summary=summary_data)
    if result.outcome in {FetchOutcome.PARTIAL, FetchOutcome.BLOCKED}:
        return OperationResult(
            status=OperationStatus.PARTIAL,
            error_code=result.error_code,
            error_message=result.error_message,
            result_summary=summary_data,
            retryable=False,
        )
    return OperationResult(
        status=OperationStatus.FAILED,
        error_code=result.error_code or summary.error_code or "fetch_failed",
        error_message=result.error_message,
        result_summary=summary_data,
        retryable=_is_retryable_fetch_failure(result),
        retry_after_seconds=result.retry_after_seconds,
    )


def _is_retryable_fetch_failure(result) -> bool:
    """Retry only temporary transport/server pressure, never policy or bad-input failures."""
    if result.http_status is not None:
        if result.http_status in {408, 425, 429} or result.http_status >= 500:
            return True
        if 400 <= result.http_status < 500:
            return False
    if result.error_category in {
        ErrorCategory.VALIDATION,
        ErrorCategory.ELIGIBILITY,
        ErrorCategory.AUTHENTICATION,
        ErrorCategory.PARSING,
        ErrorCategory.PERSISTENCE,
        ErrorCategory.CONFLICT,
    }:
        return False
    code = (result.error_code or "").lower()
    nonretryable_markers = (
        "credential",
        "permission",
        "auth",
        "invalid",
        "unknown",
        "unsupported",
        "unaudited",
        "schema",
        "parse",
        "malformed",
    )
    return not any(marker in code for marker in nonretryable_markers)


def _execute_production_fetch(
    source: SourceDefinition,
    operation_id: int,
    checkpoint: Callable[[str], None],
    requested_scope: Mapping[str, object],
) -> SourceFetchSummary:
    """Keep the request process outside the web request and every DB transaction."""

    async def run() -> SourceFetchSummary:
        with create_session() as session:
            if bool(requested_scope.get("trial", False)):
                decision = evaluate_trial_eligibility(
                    source, SourceRepository(session).latest_probe_snapshot(source.id)
                )
                if not decision.eligible:
                    error_code = f"eligibility_trial_{decision.code or 'ineligible'}"
                    return SourceFetchSummary(
                        source.id,
                        FetchResult(
                            outcome=FetchOutcome.BLOCKED,
                            error_code=error_code,
                            error_message=decision.reason,
                        ),
                        error_code=error_code,
                    )
            policy = HttpPolicy.default()
            try:
                return await IngestionService(session, FetcherFactory(policy)).fetch_source(
                    source,
                    approved_only=not bool(
                        requested_scope.get("one_off", False)
                        or requested_scope.get("trial", False)
                    ),
                    max_items=(
                        requested_scope.get("max_items")
                        if isinstance(requested_scope.get("max_items"), int)
                        else None
                    ),
                    dry_run=bool(requested_scope.get("dry_run", False)),
                    operation_run_id=operation_id,
                    checkpoint=checkpoint,
                )
            finally:
                await policy.client.aclose()

    return asyncio.run(run())
