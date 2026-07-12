from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from newsradar.db.models import OperationAttemptRecord, OperationEventRecord, OperationRunRecord
from newsradar.events.runtime import EventOperationHandler
from newsradar.operations.commands import OperationCommandService
from newsradar.operations.repository import OperationRepository
from newsradar.operations.router import OperationRouter
from newsradar.operations.schema import OperationStatus
from newsradar.operations.worker import Worker
from newsradar.settings import Settings


def _postgres_engine_or_skip():
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


def test_postgres_competing_workers_claim_event_pipeline_once() -> None:
    """A real SKIP LOCKED race permits only one worker to publish an event build attempt."""
    engine = _postgres_engine_or_skip()
    suffix = uuid4().hex
    operation_id: int | None = None
    first_has_row_lock = Event()
    release_first = Event()
    try:
        with Session(engine) as setup:
            operation_id = OperationCommandService(setup).enqueue_event_pipeline(
                window_hours=24, trigger="acceptance"
            )

        class LockHoldingRepository(OperationRepository):
            def _ensure_worker(self, worker_id: str):
                first_has_row_lock.set()
                assert release_first.wait(timeout=5), "first worker was not released"
                return super()._ensure_worker(worker_id)

        router = OperationRouter(
            {"event_pipeline": EventOperationHandler.production(lambda: Session(engine))}
        )

        def consume(worker_id: str, *, hold_lock: bool = False) -> bool:
            with Session(engine) as session:
                repository = (
                    LockHoldingRepository(session) if hold_lock else OperationRepository(session)
                )
                return Worker(repository, worker_id).run_once(router)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(consume, f"event-owner-a-{suffix}", hold_lock=True)
            assert first_has_row_lock.wait(timeout=5), "first worker did not claim the operation"
            second = pool.submit(consume, f"event-owner-b-{suffix}")
            second_processed = second.result(timeout=5)
            release_first.set()
            first_processed = first.result(timeout=5)

        with Session(engine) as verify:
            operation = verify.get(OperationRunRecord, operation_id)
            attempts = verify.scalars(
                select(OperationAttemptRecord).where(
                    OperationAttemptRecord.operation_run_id == operation_id
                )
            ).all()
        assert operation is not None
        assert operation.status == OperationStatus.SUCCEEDED.value
        assert first_processed is True
        assert second_processed is False
        assert operation.attempt_count == 1
        assert len(attempts) == 1
        assert attempts[0].status == OperationStatus.SUCCEEDED.value
    finally:
        if operation_id is not None:
            with Session(engine) as cleanup:
                cleanup.execute(
                    delete(OperationEventRecord).where(
                        OperationEventRecord.operation_run_id == operation_id
                    )
                )
                cleanup.execute(
                    delete(OperationAttemptRecord).where(
                        OperationAttemptRecord.operation_run_id == operation_id
                    )
                )
                cleanup.execute(
                    delete(OperationRunRecord).where(OperationRunRecord.id == operation_id)
                )
                cleanup.commit()
        engine.dispose()
