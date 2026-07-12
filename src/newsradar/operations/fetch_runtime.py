from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from typing import Protocol

from newsradar.db.session import create_session
from newsradar.ingestion.fetchers.base import FetcherFactory, HttpPolicy
from newsradar.ingestion.schema import FetchOutcome
from newsradar.ingestion.service import IngestionService, SourceFetchSummary
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.operations.worker import OperationResult
from newsradar.sources.schema import SourceDefinition


class FetchExecutor(Protocol):
    def __call__(
        self,
        source: SourceDefinition,
        operation_id: int,
        checkpoint: Callable[[str], None],
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
        checkpoint("before_source")
        summary = self._executor(source, lease.operation_id, checkpoint)
        checkpoint("after_source")
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
        retryable=True,
    )


def _execute_production_fetch(
    source: SourceDefinition, operation_id: int, _checkpoint: Callable[[str], None]
) -> SourceFetchSummary:
    """Keep the request process outside the web request and every DB transaction."""

    async def run() -> SourceFetchSummary:
        policy = HttpPolicy.default()
        try:
            with create_session() as session:
                return await IngestionService(session, FetcherFactory(policy)).fetch_source(
                    source,
                    approved_only=True,
                    operation_run_id=operation_id,
                )
        finally:
            await policy.client.aclose()

    return asyncio.run(run())
