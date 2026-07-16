from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from newsradar.db.models import FetchRunRecord, SourceAccessMethodRecord, SourceFetchStateRecord
from newsradar.ingestion.eligibility import evaluate_fetch_eligibility
from newsradar.ingestion.fetchers.base import (
    FetcherFactory,
    FetchState,
    TrialCredentialFreeFetcherRequiredError,
)
from newsradar.ingestion.fetchers.credentials import SettingsCredentials
from newsradar.ingestion.repository import ItemAction, RawItemRepository
from newsradar.ingestion.schema import FetchOutcome, FetchResult
from newsradar.operations.logging import redact
from newsradar.operations.schema import ErrorCategory
from newsradar.operations.worker import OperationCancelled
from newsradar.settings import Settings, get_settings
from newsradar.sources.schema import SourceDefinition


@dataclass(frozen=True)
class SourceFetchSummary:
    source_id: str
    result: FetchResult
    fetch_run_id: int | None = None
    error_code: str | None = None


class SourceFetchLockedError(Exception):
    pass


class IngestionService:
    """Coordinates network-only fetchers with short, separately committed writes."""

    def __init__(
        self,
        session: Session,
        factory: FetcherFactory,
        *,
        configured_env: set[str] | None = None,
        settings: Settings | None = None,
    ):
        self.session, self.factory = session, factory
        self.settings = settings or get_settings()
        self.configured_env = (
            configured_env
            if configured_env is not None
            else SettingsCredentials(self.settings).configured_names()
        )

    async def fetch_source(
        self,
        source: SourceDefinition,
        *,
        approved_only: bool = False,
        credential_free_only: bool = False,
        max_items: int | None = None,
        dry_run: bool = False,
        operation_run_id: int | None = None,
        checkpoint: Callable[[str], None] | None = None,
    ) -> SourceFetchSummary:
        decision = evaluate_fetch_eligibility(
            source,
            approved_only=approved_only,
            configured_env=self.configured_env,
            hard_block_reason=None,
            credential_free_only=credential_free_only,
        )
        if not decision.allowed or decision.access_method is None:
            result = FetchResult(
                outcome=FetchOutcome.BLOCKED,
                error_code=decision.error_code,
                error_message=decision.reason,
            )
            return SourceFetchSummary(source.id, result, error_code=decision.error_code)
        try:
            lock_connection = self._acquire_advisory_lock(source.id)
        except SourceFetchLockedError:
            result = FetchResult(
                outcome=FetchOutcome.BLOCKED,
                error_code="source_fetch_locked",
                error_message="A fetch for this source is already running",
            )
            return SourceFetchSummary(source.id, result, error_code=result.error_code)
        try:
            return await self._fetch_eligible(
                source,
                decision.access_method,
                credential_free_only=credential_free_only,
                max_items=max_items,
                dry_run=dry_run,
                operation_run_id=operation_run_id,
                checkpoint=checkpoint,
            )
        finally:
            self._release_advisory_lock(lock_connection, source.id)

    async def _fetch_eligible(
        self,
        source: SourceDefinition,
        method,
        *,
        credential_free_only: bool,
        max_items: int | None,
        dry_run: bool,
        operation_run_id: int | None,
        checkpoint: Callable[[str], None] | None,
    ) -> SourceFetchSummary:
        limit = min(
            max_items or source.ingestion.max_items_per_run, source.ingestion.max_items_per_run
        )
        try:
            fetcher = (
                self.factory.for_method(method, credential_free_only=True)
                if credential_free_only
                else self.factory.for_method(method)
            )
        except TrialCredentialFreeFetcherRequiredError as error:
            result = FetchResult(
                outcome=FetchOutcome.BLOCKED,
                error_code=f"eligibility_trial_{error.code}",
                error_message=error.reason,
            )
            return SourceFetchSummary(source.id, result, error_code=result.error_code)
        method_id, state = self._state(source.id, str(method.url))
        # Fetching is intentionally outside every database transaction.
        try:
            if checkpoint is not None:
                checkpoint("before_network")
            async with asyncio.timeout(self.settings.source_timeout_seconds):
                result = await fetcher.fetch(source, method, state, limit)
            if checkpoint is not None:
                checkpoint("after_network")
        except TimeoutError:
            result = FetchResult(
                outcome=FetchOutcome.FAILED,
                error_category=ErrorCategory.TRANSPORT,
                error_code="source_timeout",
                error_message=(
                    f"Source fetch exceeded {self.settings.source_timeout_seconds:g} seconds"
                ),
            )
        except OperationCancelled:
            raise
        except Exception as exc:
            result = FetchResult(
                outcome=FetchOutcome.FAILED, error_code="fetch_failed", error_message=str(exc)
            )
        if dry_run:
            return SourceFetchSummary(source.id, result, error_code=result.error_code)
        fetch_run = self._start_run(source.id, method_id, operation_run_id)
        if result.outcome in {
            FetchOutcome.SUCCEEDED,
            FetchOutcome.PARTIAL,
            FetchOutcome.NO_CHANGE,
        }:
            counts = {action: 0 for action in ItemAction}
            repository = RawItemRepository(self.session)
            for item in result.items:
                if checkpoint is not None:
                    checkpoint("before_item")
                try:
                    written = repository.upsert(fetch_run.id, source.id, item)
                except Exception:
                    # A malformed provider record must not leave the entire run
                    # pending or prevent later items from being persisted.
                    self.session.rollback()
                    written = repository.record_failure(
                        fetch_run.id, source.id, item, "item_persistence_failed"
                    )
                counts[written.action] += 1
                # Keep each unit of work bounded; repository uses savepoints for item failures.
                self.session.commit()
                if checkpoint is not None:
                    checkpoint("after_item")
            result = result.model_copy(
                update={
                    "outcome": (
                        FetchOutcome.PARTIAL if counts[ItemAction.FAILED] else result.outcome
                    ),
                    "items_inserted": counts[ItemAction.INSERTED],
                    "items_updated": counts[ItemAction.UPDATED],
                    "items_unchanged": counts[ItemAction.UNCHANGED],
                    "items_skipped": counts[ItemAction.SKIPPED],
                    "items_failed": counts[ItemAction.FAILED],
                }
            )
            self._commit_success(fetch_run, source.id, method_id, result)
        else:
            self._finish_run(fetch_run, source.id, method_id, result)
        return SourceFetchSummary(source.id, result, fetch_run.id, result.error_code)

    def _acquire_advisory_lock(self, source_id: str) -> Connection | None:
        if self.session.bind is None or self.session.bind.dialect.name != "postgresql":
            return None
        connection = self.session.bind.connect()
        try:
            acquired = bool(
                connection.scalar(select(func.pg_try_advisory_lock(func.hashtext(source_id))))
            )
            connection.rollback()
            if not acquired:
                raise SourceFetchLockedError
            return connection
        except Exception:
            connection.close()
            raise

    @staticmethod
    def _release_advisory_lock(connection: Connection | None, source_id: str) -> None:
        if connection is None:
            return
        try:
            connection.scalar(select(func.pg_advisory_unlock(func.hashtext(source_id))))
        finally:
            connection.rollback()
            connection.close()

    def _state(self, source_id: str, url: str) -> tuple[int | None, FetchState]:
        try:
            method = self.session.scalar(
                select(SourceAccessMethodRecord).where(
                    SourceAccessMethodRecord.source_id == source_id,
                    SourceAccessMethodRecord.url == url,
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
            return method.id, (
                FetchState(state.etag, state.last_modified, state.cursor) if state else FetchState()
            )
        finally:
            # A SELECT autostarts a SQLAlchemy transaction; no network may run inside it.
            if self.session.in_transaction():
                self.session.rollback()

    def _start_run(
        self, source_id: str, method_id: int | None, operation_run_id: int | None
    ) -> FetchRunRecord:
        run = FetchRunRecord(
            source_id=source_id, access_method_id=method_id, operation_run_id=operation_run_id
        )
        self.session.add(run)
        self.session.commit()
        return run

    def _finish_run(
        self,
        run: FetchRunRecord,
        source_id: str,
        method_id: int | None,
        result: FetchResult,
    ) -> None:
        run.outcome, run.finished_at, run.http_status = (
            result.outcome.value,
            datetime.now(UTC),
            result.http_status,
        )
        run.error_code = result.error_code
        run.error_message = redact(result.error_message or "") or None
        if method_id is not None:
            state = self._fetch_state(source_id, method_id)
            state.consecutive_failures += 1
            state.last_failure_at = datetime.now(UTC)
            state.last_error_code = result.error_code
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
            state = self._fetch_state(source_id, method_id)
            state.etag, state.last_modified, state.cursor, state.last_success_at = (
                result.etag,
                result.last_modified,
                result.next_cursor,
                datetime.now(UTC),
            )
            state.consecutive_failures = 0
            state.last_failure_at = None
            state.last_error_code = None
        self.session.commit()

    def _fetch_state(self, source_id: str, method_id: int) -> SourceFetchStateRecord:
        state = self.session.scalar(
            select(SourceFetchStateRecord).where(
                SourceFetchStateRecord.source_id == source_id,
                SourceFetchStateRecord.access_method_id == method_id,
            )
        )
        if state is None:
            state = SourceFetchStateRecord(
                source_id=source_id,
                access_method_id=method_id,
                consecutive_failures=0,
            )
            self.session.add(state)
        return state
