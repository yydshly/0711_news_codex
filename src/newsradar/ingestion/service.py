from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import FetchRunRecord, SourceAccessMethodRecord, SourceFetchStateRecord
from newsradar.ingestion.eligibility import evaluate_fetch_eligibility
from newsradar.ingestion.fetchers.base import FetcherFactory, FetchState
from newsradar.ingestion.repository import ItemAction, RawItemRepository
from newsradar.ingestion.schema import FetchOutcome, FetchResult
from newsradar.sources.schema import SourceDefinition


@dataclass(frozen=True)
class SourceFetchSummary:
    source_id: str
    result: FetchResult
    fetch_run_id: int | None = None
    error_code: str | None = None


class IngestionService:
    """Coordinates network-only fetchers with short, separately committed writes."""

    def __init__(
        self, session: Session, factory: FetcherFactory, *, configured_env: set[str] | None = None
    ):
        self.session, self.factory = session, factory
        self.configured_env = configured_env if configured_env is not None else set(os.environ)

    async def fetch_source(
        self,
        source: SourceDefinition,
        *,
        approved_only: bool = False,
        max_items: int | None = None,
        dry_run: bool = False,
        operation_run_id: int | None = None,
    ) -> SourceFetchSummary:
        decision = evaluate_fetch_eligibility(
            source,
            approved_only=approved_only,
            configured_env=self.configured_env,
            hard_block_reason=None,
        )
        if not decision.allowed or decision.access_method is None:
            result = FetchResult(
                outcome=FetchOutcome.BLOCKED,
                error_code=decision.error_code,
                error_message=decision.reason,
            )
            return SourceFetchSummary(source.id, result, error_code=decision.error_code)
        method = decision.access_method
        limit = min(
            max_items or source.ingestion.max_items_per_run, source.ingestion.max_items_per_run
        )
        method_id, state = self._state(source.id, str(method.url))
        # Fetching is intentionally outside every database transaction.
        try:
            result = await self.factory.for_method(method).fetch(source, method, state, limit)
        except Exception as exc:
            result = FetchResult(
                outcome=FetchOutcome.FAILED, error_code="fetch_failed", error_message=str(exc)
            )
        if dry_run:
            return SourceFetchSummary(source.id, result, error_code=result.error_code)
        fetch_run = self._start_run(source.id, method_id, operation_run_id)
        if result.outcome in {FetchOutcome.SUCCEEDED, FetchOutcome.PARTIAL}:
            counts = {action: 0 for action in ItemAction}
            repository = RawItemRepository(self.session)
            for item in result.items:
                written = repository.upsert(fetch_run.id, source.id, item)
                counts[written.action] += 1
                # Keep each unit of work bounded; repository uses savepoints for item failures.
                self.session.commit()
            result = result.model_copy(
                update={
                    "items_inserted": counts[ItemAction.INSERTED],
                    "items_updated": counts[ItemAction.UPDATED],
                    "items_unchanged": counts[ItemAction.UNCHANGED],
                    "items_skipped": counts[ItemAction.SKIPPED],
                    "items_failed": counts[ItemAction.FAILED],
                }
            )
            self._commit_success(fetch_run, source.id, method_id, result)
        else:
            self._finish_run(fetch_run, result)
        return SourceFetchSummary(source.id, result, fetch_run.id, result.error_code)

    def _state(self, source_id: str, url: str) -> tuple[int | None, FetchState]:
        method = self.session.scalar(
            select(SourceAccessMethodRecord).where(
                SourceAccessMethodRecord.source_id == source_id, SourceAccessMethodRecord.url == url
            )
        )
        if method is None:
            return None, FetchState()
        state = self.session.scalar(
            select(SourceFetchStateRecord).where(
                SourceFetchStateRecord.source_id == source_id,
                SourceFetchStateRecord.access_method_id == method.id,
            )
        )
        return method.id, FetchState(
            state.etag, state.last_modified, state.cursor
        ) if state else FetchState()

    def _start_run(
        self, source_id: str, method_id: int | None, operation_run_id: int | None
    ) -> FetchRunRecord:
        run = FetchRunRecord(
            source_id=source_id, access_method_id=method_id, operation_run_id=operation_run_id
        )
        self.session.add(run)
        self.session.commit()
        return run

    def _finish_run(self, run: FetchRunRecord, result: FetchResult) -> None:
        run.outcome, run.finished_at, run.http_status = (
            result.outcome.value,
            datetime.now(UTC),
            result.http_status,
        )
        run.error_code, run.error_message = result.error_code, result.error_message
        self.session.commit()

    def _commit_success(
        self, run: FetchRunRecord, source_id: str, method_id: int | None, result: FetchResult
    ) -> None:
        run.outcome, run.finished_at, run.http_status = (
            result.outcome.value,
            datetime.now(UTC),
            result.http_status,
        )
        run.final_url, run.etag, run.last_modified, run.next_cursor = (
            (str(result.final_url) if result.final_url else None),
            result.etag,
            result.last_modified,
            result.next_cursor,
        )
        run.items_received, run.items_inserted, run.items_updated = (
            result.items_received,
            result.items_inserted,
            result.items_updated,
        )
        run.items_unchanged, run.items_skipped, run.items_failed = (
            result.items_unchanged,
            result.items_skipped,
            result.items_failed,
        )
        if method_id is not None:
            state = self.session.scalar(
                select(SourceFetchStateRecord).where(
                    SourceFetchStateRecord.source_id == source_id,
                    SourceFetchStateRecord.access_method_id == method_id,
                )
            )
            if state is None:
                state = SourceFetchStateRecord(source_id=source_id, access_method_id=method_id)
                self.session.add(state)
            state.etag, state.last_modified, state.cursor, state.last_success_at = (
                result.etag,
                result.last_modified,
                result.next_cursor,
                datetime.now(UTC),
            )
            state.consecutive_failures = 0
        self.session.commit()
