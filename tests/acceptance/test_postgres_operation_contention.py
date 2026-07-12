from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from newsradar.db.models import (
    FetchRunRecord,
    OperationAttemptRecord,
    OperationEventRecord,
    OperationRunRecord,
    SourceDefinitionRecord,
    WorkerRecord,
)
from newsradar.ingestion.schema import FetchOutcome, FetchResult
from newsradar.ingestion.service import SourceFetchSummary
from newsradar.operations.fetch_runtime import FetchOperationHandler
from newsradar.operations.repository import OperationRepository
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.operations.worker import Worker
from newsradar.settings import Settings
from newsradar.sources.schema import SourceDefinition


def _postgres_engine_or_skip():
    """Use the configured project-local PostgreSQL only; never emulate this on SQLite."""
    database_url = Settings().database_url
    if not database_url or not database_url.startswith("postgresql"):
        pytest.skip("project-local PostgreSQL DATABASE_URL is not configured")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if connection.dialect.name != "postgresql":
                pytest.skip("configured database is not PostgreSQL")
    except SQLAlchemyError as error:
        engine.dispose()
        pytest.skip(f"project-local PostgreSQL is unavailable: {error.__class__.__name__}")
    return engine


def _source_definition(source_id: str) -> SourceDefinition:
    return SourceDefinition.model_validate(
        {
            "id": source_id,
            "name": "PostgreSQL contention acceptance source",
            "status": "active",
            "nature": "first_party",
            "roles": ["discovery"],
            "language": "en",
            "topics": ["ai"],
            "authority_score": 5,
            "poll_interval_minutes": 60,
            "official_identity_url": "https://acceptance.example.test",
            "access_methods": [
                {"kind": "rss", "url": "https://acceptance.example.test/feed", "priority": 1}
            ],
            "expected_fields": ["title", "canonical_url", "published_at"],
            "risk": {
                "terms": 0,
                "authentication": 0,
                "stability": 0,
                "data_quality": 0,
                "operating_cost": 0,
            },
            "ingestion": {"enabled": True, "approved_at": "2026-07-12T00:00:00Z"},
        }
    )


def test_postgres_competing_workers_claim_one_operation_once_and_write_one_fetch_run() -> None:
    """A same-operation race must make exactly one real PostgreSQL worker the owner."""
    engine = _postgres_engine_or_skip()
    suffix = uuid4().hex
    source_id = f"postgres-contention-{suffix}"
    worker_ids = (f"postgres-contention-a-{suffix}", f"postgres-contention-b-{suffix}")
    operation_id: int | None = None
    try:
        with Session(engine) as setup:
            setup.add(
                SourceDefinitionRecord(
                    id=source_id,
                    name="PostgreSQL contention acceptance source",
                    status="active",
                    nature="first_party",
                    language="en",
                    roles=["discovery"],
                    topics=["ai"],
                    authority_score=5,
                    poll_interval_minutes=60,
                    expected_fields=["title"],
                    definition_hash=suffix,
                )
            )
            operation = OperationRepository(setup).enqueue(
                OperationType.FETCH, {"source_id": source_id}
            )
            operation_id = operation.id

        def execute(_source, claimed_operation_id, checkpoint, requested_scope):
            checkpoint("before_local_fetch_run")
            with Session(engine) as fetch_session:
                fetch_run = FetchRunRecord(
                    source_id=source_id, operation_run_id=claimed_operation_id
                )
                fetch_session.add(fetch_run)
                fetch_session.commit()
                fetch_run_id = fetch_run.id
            checkpoint("after_local_fetch_run")
            return SourceFetchSummary(
                source_id,
                FetchResult(outcome=FetchOutcome.SUCCEEDED),
                fetch_run_id=fetch_run_id,
            )

        handler = FetchOperationHandler([_source_definition(source_id)], execute)

        first_worker_has_row_lock = Event()
        release_first_worker = Event()

        class _LockHoldingRepository(OperationRepository):
            def _ensure_worker(self, worker_id: str) -> WorkerRecord:
                # lease_next has already selected this operation FOR UPDATE at this point.
                first_worker_has_row_lock.set()
                assert release_first_worker.wait(timeout=5), "test did not release first worker"
                return super()._ensure_worker(worker_id)

        def consume(worker_id: str, *, hold_row_lock: bool = False) -> bool:
            with Session(engine) as session:
                repository = (
                    _LockHoldingRepository(session)
                    if hold_row_lock
                    else OperationRepository(session)
                )
                return Worker(repository, worker_id).run_once(handler)

        # The first worker deliberately holds the database row lock.  The second session then
        # calls the unmodified production repository and must be skipped by FOR UPDATE SKIP LOCKED.
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(consume, worker_ids[0], hold_row_lock=True)
            assert first_worker_has_row_lock.wait(timeout=5), "first worker did not obtain row lock"
            second = pool.submit(consume, worker_ids[1])
            second_processed = second.result(timeout=5)
            release_first_worker.set()
            first_processed = first.result(timeout=5)

        with Session(engine) as verify:
            operation = verify.get(OperationRunRecord, operation_id)
            assert operation is not None
            assert operation.status == OperationStatus.SUCCEEDED.value
            assert operation.attempt_count == 1
            attempts = verify.scalars(
                select(OperationAttemptRecord).where(
                    OperationAttemptRecord.operation_run_id == operation_id
                )
            ).all()
            fetch_runs = verify.scalars(
                select(FetchRunRecord).where(FetchRunRecord.operation_run_id == operation_id)
            ).all()
            assert first_processed is True
            assert second_processed is False
            assert len(attempts) == 1
            assert attempts[0].attempt_number == 1
            assert attempts[0].status == OperationStatus.SUCCEEDED.value
            assert len(fetch_runs) == 1
            assert fetch_runs[0].source_id == source_id
    finally:
        if operation_id is not None:
            with Session(engine) as cleanup:
                cleanup.execute(
                    delete(OperationEventRecord).where(
                        OperationEventRecord.operation_run_id == operation_id
                    )
                )
                cleanup.execute(
                    delete(FetchRunRecord).where(FetchRunRecord.operation_run_id == operation_id)
                )
                cleanup.execute(
                    delete(OperationAttemptRecord).where(
                        OperationAttemptRecord.operation_run_id == operation_id
                    )
                )
                cleanup.execute(
                    delete(OperationRunRecord).where(OperationRunRecord.id == operation_id)
                )
                cleanup.execute(delete(WorkerRecord).where(WorkerRecord.worker_id.in_(worker_ids)))
                cleanup.execute(
                    delete(SourceDefinitionRecord).where(SourceDefinitionRecord.id == source_id)
                )
                cleanup.commit()
        engine.dispose()
