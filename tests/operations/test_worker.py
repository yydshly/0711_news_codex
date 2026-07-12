from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from newsradar.db.models import Base, OperationEventRecord
from newsradar.operations.repository import OperationRepository
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.operations.worker import Worker


def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_worker_renews_heartbeat_while_handler_runs() -> None:
    with session() as db:
        repository = OperationRepository(db)
        repository.enqueue(OperationType.FETCH, {})
        renewals: list[int] = []
        worker = Worker(
            repository, "worker", heartbeat=lambda lease: renewals.append(lease.operation_id)
        )

        assert worker.run_once(lambda lease, checkpoint: checkpoint("source"))

        assert renewals == [1]


def test_worker_closes_claim_transaction_before_running_handler() -> None:
    with session() as db:
        repository = OperationRepository(db)
        repository.enqueue(OperationType.FETCH, {})
        transaction_states: list[bool] = []

        Worker(repository, "worker").run_once(
            lambda lease, checkpoint: transaction_states.append(db.in_transaction())
        )

        assert transaction_states == [False]


def test_worker_uses_injected_clock_for_deterministic_heartbeat_timing() -> None:
    with session() as db:
        repository = OperationRepository(db)
        repository.enqueue(OperationType.FETCH, {})
        instants = iter((0.0, 5.0, 10.0))
        renewals: list[int] = []
        worker = Worker(
            repository,
            "worker",
            heartbeat=lambda lease: renewals.append(lease.operation_id),
            clock=lambda: next(instants),
            heartbeat_interval_seconds=10,
        )

        worker.run_once(lambda lease, checkpoint: (checkpoint("source"), checkpoint("page")))

        assert renewals == [1]


def test_worker_stops_at_source_boundary_when_cancellation_is_requested() -> None:
    with session() as db:
        repository = OperationRepository(db)
        operation = repository.enqueue(OperationType.FETCH, {})

        def handler(lease: object, checkpoint: object) -> None:
            repository.request_cancel(operation.id)
            checkpoint("page")  # type: ignore[operator]

        assert Worker(repository, "worker").run_once(handler) is False
        assert db.get(type(operation), operation.id).status == OperationStatus.CANCELLED  # type: ignore[union-attr]


def test_worker_records_scrubbed_failure_event_for_uncaught_exception() -> None:
    with session() as db:
        repository = OperationRepository(db)
        repository.enqueue(OperationType.FETCH, {})

        Worker(repository, "worker").run_once(
            lambda lease, checkpoint: (_ for _ in ()).throw(RuntimeError("Bearer secret-token"))
        )

        event = db.scalar(select(OperationEventRecord))
        assert event is not None
        assert "secret-token" not in event.message
        assert event.error_code == "internal"
