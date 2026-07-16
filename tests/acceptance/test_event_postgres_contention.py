import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from newsradar.ai.minimax import ModelUsage
from newsradar.db.models import (
    EventModelRunRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    ModelUsageRecord,
    OperationAttemptRecord,
    OperationEventRecord,
    OperationRunRecord,
)
from newsradar.events.repository import EventRepository
from newsradar.events.runtime import EventOperationHandler
from newsradar.events.schema import (
    EventEnrichment,
    EventStatus,
    PublishedEvent,
    ScoreBreakdown,
)
from newsradar.operations.commands import OperationCommandService
from newsradar.operations.repository import OperationRepository
from newsradar.operations.router import OperationRouter
from newsradar.operations.schema import OperationStatus
from newsradar.operations.worker import Worker
from newsradar.settings import Settings


def _postgres_engine_or_skip():
    if os.getenv("NEWSRADAR_RUN_POSTGRES_ACCEPTANCE") != "1":
        pytest.skip("set NEWSRADAR_RUN_POSTGRES_ACCEPTANCE=1 to run real PostgreSQL acceptance")
    database_url = Settings().database_url
    if not database_url or not database_url.startswith("postgresql"):
        pytest.skip("project-local PostgreSQL DATABASE_URL is not configured")
    engine = create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
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
            # The winner executes the real event pipeline over the project-local
            # dataset; only the competing SKIP LOCKED claimant must return quickly.
            first_processed = first.result(timeout=60)

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


def test_postgres_concurrent_first_publish_of_same_canonical_event_is_idempotent() -> None:
    engine = _postgres_engine_or_skip()
    canonical_key = f"contention-{uuid4().hex}"
    insertion_barrier = Barrier(2)

    def snapshot() -> PublishedEvent:
        return PublishedEvent(
            canonical_key=canonical_key,
            status=EventStatus.EMERGING,
            enrichment=EventEnrichment(
                zh_title="并发事件",
                zh_summary="两个 Operation 同时首次发布同一事件。",
                why_it_matters="唯一键竞争必须安全收敛。",
                origin="rule_fallback",
                confidence=0,
            ),
            score=ScoreBreakdown(
                ai_relevance=80,
                source_coverage=35,
                source_authority=80,
                recency=100,
                engagement_velocity=0,
                novelty=100,
                importance=70,
                credibility=35,
                heat=56,
                rule_version="score-v2",
                reasons=("fixture",),
            ),
        )

    def publish(operation_id: int) -> int:
        with Session(engine) as session:
            def synchronize_first_insert(session, flush_context, instances) -> None:
                del flush_context, instances
                if any(
                    isinstance(row, EventRecord)
                    and row.canonical_key == canonical_key
                    for row in session.new
                ):
                    insertion_barrier.wait(timeout=10)

            sqlalchemy_event.listen(session, "before_flush", synchronize_first_insert)
            record = EventRepository(session).publish_complete_event(
                snapshot(),
                operation_id,
                model_usages=(
                    ModelUsage(
                        purpose="event_enrichment",
                        model=f"contention-operation-{operation_id}",
                        input_tokens=operation_id,
                        output_tokens=1,
                        latency_ms=1,
                        outcome="success",
                    ),
                ),
            )
            event_id = record.id
            session.commit()
            return event_id

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = tuple(pool.submit(publish, operation_id) for operation_id in (901, 902))
            event_ids = tuple(future.result(timeout=20) for future in futures)

        with Session(engine) as verify:
            event_rows = tuple(
                verify.scalars(
                    select(EventRecord).where(EventRecord.canonical_key == canonical_key)
                )
            )
            version_rows = tuple(
                verify.scalars(
                    select(EventVersionRecord).where(
                        EventVersionRecord.event_id == event_rows[0].id
                    )
                )
            )
            run_rows = tuple(
                verify.scalars(
                    select(EventModelRunRecord).where(
                        EventModelRunRecord.event_id == event_rows[0].id
                    )
                )
            )
            usage_rows = tuple(
                verify.scalars(
                    select(ModelUsageRecord).where(
                        ModelUsageRecord.id.in_(
                            [row.model_usage_id for row in run_rows]
                        )
                    )
                )
            )

        assert len(set(event_ids)) == 1
        assert len(event_rows) == 1
        assert event_rows[0].current_version_number == 1
        assert len(version_rows) == 1
        assert len(run_rows) == 2
        assert {row.model for row in usage_rows} == {
            "contention-operation-901",
            "contention-operation-902",
        }
    finally:
        with Session(engine) as cleanup:
            event_id = cleanup.scalar(
                select(EventRecord.id).where(EventRecord.canonical_key == canonical_key)
            )
            if event_id is not None:
                usage_ids = tuple(
                    cleanup.scalars(
                        select(EventModelRunRecord.model_usage_id).where(
                            EventModelRunRecord.event_id == event_id
                        )
                    )
                )
                cleanup.execute(
                    delete(EventModelRunRecord).where(
                        EventModelRunRecord.event_id == event_id
                    )
                )
                if usage_ids:
                    cleanup.execute(
                        delete(ModelUsageRecord).where(ModelUsageRecord.id.in_(usage_ids))
                    )
                cleanup.execute(
                    delete(EventScoreRecord).where(EventScoreRecord.event_id == event_id)
                )
                cleanup.execute(
                    delete(EventVersionRecord).where(EventVersionRecord.event_id == event_id)
                )
                cleanup.execute(delete(EventRecord).where(EventRecord.id == event_id))
                cleanup.commit()
        engine.dispose()
