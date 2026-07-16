from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event, Lock, Thread

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from newsradar.db.models import Base, OperationEventRecord, OperationRunRecord, WorkerRecord
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


def test_worker_without_operation_persists_idle_heartbeat() -> None:
    with session() as db:
        worker = Worker(OperationRepository(db), "idle-worker")

        assert worker.run_once(lambda *_: None) is False

        record = db.get(WorkerRecord, "idle-worker")
        assert record is not None
        assert record.status == "idle"
        assert record.current_operation_run_id is None
        assert record.last_heartbeat_at is not None


def test_idle_heartbeat_clears_missing_operation_reference() -> None:
    with session() as db:
        db.add(
            WorkerRecord(
                worker_id="orphan-worker",
                hostname="local",
                started_at=datetime.now(UTC),
                last_heartbeat_at=datetime.now(UTC),
                status="running",
                current_operation_run_id=999,
            )
        )
        db.commit()

        assert Worker(OperationRepository(db), "orphan-worker").run_once(lambda *_: None) is False

        record = db.get(WorkerRecord, "orphan-worker")
        assert record.status == "idle"
        assert record.current_operation_run_id is None


def test_finished_operation_returns_worker_to_idle() -> None:
    with session() as db:
        operation = OperationRepository(db).enqueue(OperationType.FETCH, {})

        assert Worker(OperationRepository(db), "worker-a").run_once(lambda *_: None) is True

        record = db.get(WorkerRecord, "worker-a")
        completed = db.get(OperationRunRecord, operation.id)
        assert record is not None
        assert record.status == "idle"
        assert record.current_operation_run_id is None
        assert completed is not None
        assert completed.status == OperationStatus.SUCCEEDED


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


def test_slow_handler_renews_lease_so_second_worker_cannot_reclaim(tmp_path) -> None:
    """Production-style I/O must retain ownership beyond the original short lease."""
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'operations.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as seed:
        OperationRepository(seed).enqueue(OperationType.FETCH, {})

    started, release = Event(), Event()

    def guard(lease):
        with Session(engine) as monitor_session:
            monitor = OperationRepository(monitor_session)
            renewed = monitor.renew_lease(lease, lease_seconds=1)
            return renewed and not monitor.is_cancel_requested(lease)

    def run_slow_worker() -> None:
        with Session(engine) as worker_session:
            Worker(
                OperationRepository(worker_session),
                "worker-a",
                lease_seconds=0.05,
                lease_guard=guard,
                monitor_interval_seconds=0.01,
            ).run_once(
                lambda lease, checkpoint: (
                    started.set(),
                    release.wait(timeout=2),
                    checkpoint("done"),
                )
            )

    thread = Thread(target=run_slow_worker)
    thread.start()
    assert started.wait(timeout=1)
    time.sleep(0.1)
    with Session(engine) as contender_session:
        assert OperationRepository(contender_session).lease_next("worker-b") is None
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_slow_handler_observes_cancellation_from_background_lease_monitor(tmp_path) -> None:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'cancellation.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as seed:
        operation = OperationRepository(seed).enqueue(OperationType.FETCH, {})
        operation_id = operation.id

    started, release = Event(), Event()

    def guard(lease):
        with Session(engine) as monitor_session:
            monitor = OperationRepository(monitor_session)
            renewed = monitor.renew_lease(lease, lease_seconds=1)
            return renewed and not monitor.is_cancel_requested(lease)

    def run_slow_worker() -> None:
        with Session(engine) as worker_session:
            Worker(
                OperationRepository(worker_session),
                "worker-a",
                lease_guard=guard,
                monitor_interval_seconds=0.01,
            ).run_once(
                lambda lease, checkpoint: (
                    started.set(),
                    release.wait(timeout=2),
                    checkpoint("after_io"),
                )
            )

    thread = Thread(target=run_slow_worker)
    thread.start()
    assert started.wait(timeout=1)
    with Session(engine) as canceller_session:
        assert OperationRepository(canceller_session).request_cancel(operation_id)
    time.sleep(0.05)
    release.set()
    thread.join(timeout=2)
    with Session(engine) as verify_session:
        record = verify_session.get(OperationRunRecord, operation_id)
        assert record is not None
        assert record.status == OperationStatus.CANCELLED


def test_monitored_handler_does_not_use_owner_session_from_background_thread() -> None:
    with session() as db:
        repository = OperationRepository(db)
        repository.enqueue(OperationType.FETCH, {})

        processed = Worker(
            repository,
            "worker",
            lease_guard=lambda lease: True,
            monitor_interval_seconds=0.01,
        ).run_once(lambda lease, checkpoint: checkpoint("background"))

    assert processed is True


def test_worker_serializes_concurrent_checkpoint_guards() -> None:
    with session() as db:
        repository = OperationRepository(db)
        repository.enqueue(OperationType.FETCH, {})
        start = Barrier(4)
        release = Event()
        counter_lock = Lock()
        active = 0
        max_active = 0

        def guard(_lease) -> bool:
            nonlocal active, max_active
            with counter_lock:
                active += 1
                max_active = max(max_active, active)
            release.wait(timeout=1)
            with counter_lock:
                active -= 1
            return True

        def handler(_lease, checkpoint) -> None:
            def run_checkpoint(index: int) -> None:
                start.wait(timeout=1)
                checkpoint(f"parallel-{index}")

            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(run_checkpoint, index) for index in range(3)]
                start.wait(timeout=1)
                time.sleep(0.05)
                release.set()
                for future in futures:
                    future.result(timeout=1)

        processed = Worker(
            repository,
            "worker",
            lease_guard=guard,
        ).run_once(handler)

        assert processed is True
        assert max_active == 1
