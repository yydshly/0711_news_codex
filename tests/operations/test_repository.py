from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from newsradar.db.models import Base, OperationAttemptRecord, OperationRunRecord
from newsradar.operations.repository import OperationRepository
from newsradar.operations.schema import OperationStatus, OperationType


def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_enqueue_and_lease_next_select_ready_operations_fifo_and_binds_attempt() -> None:
    with session() as db:
        repository = OperationRepository(db)
        first = repository.enqueue(OperationType.FETCH, {"source_id": "one"})
        second = repository.enqueue(OperationType.FETCH, {"source_id": "two"})

        lease = repository.lease_next("worker-a")

        assert lease is not None
        assert lease.operation_id == first.id
        assert lease.attempt_number == 1
        assert db.get(OperationRunRecord, second.id).status == OperationStatus.QUEUED
        attempt = db.scalar(select(OperationAttemptRecord))
        assert attempt is not None and attempt.operation_run_id == first.id


def test_lease_query_uses_skip_locked_for_postgresql_workers() -> None:
    with session() as db:
        statement = OperationRepository(db)._next_ready_statement()

        compiled = str(statement.compile(dialect=postgresql.dialect()))

        assert "FOR UPDATE SKIP LOCKED" in compiled


def test_lease_renews_and_expired_lease_is_reclaimed() -> None:
    with session() as db:
        repository = OperationRepository(db)
        operation = repository.enqueue(OperationType.FETCH, {})
        lease = repository.lease_next("worker-a", lease_seconds=1)
        assert lease is not None
        assert repository.renew_lease(lease, lease_seconds=60)
        db.get(OperationRunRecord, operation.id).lease_expires_at = datetime.now(UTC) - timedelta(
            seconds=1
        )  # type: ignore[union-attr]
        reclaimed = repository.lease_next("worker-b")

        assert reclaimed is not None
        assert reclaimed.operation_id == operation.id
        assert reclaimed.attempt_number == 2


def test_renew_lease_locks_attempt_before_operation_to_match_member_foreign_keys() -> None:
    """Wave-member updates validate attempt then operation FKs in this order.

    Lease maintenance must use the same order or PostgreSQL can deadlock when a
    member finishes at the same time as a heartbeat.
    """
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    locked_tables: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def record_lease_row_reads(_conn, _cursor, statement, _parameters, _context, _many):
        normalized = statement.lower()
        if not normalized.startswith("select"):
            return
        if "from operation_attempts" in normalized:
            locked_tables.append("operation_attempts")
        elif "from operation_runs" in normalized:
            locked_tables.append("operation_runs")

    with Session(engine) as db:
        repository = OperationRepository(db)
        repository.enqueue(OperationType.FETCH, {})
        lease = repository.lease_next("worker-lock-order")
        assert lease is not None
        locked_tables.clear()

        assert repository.renew_lease(lease, lease_seconds=60)

    assert locked_tables[:2] == ["operation_attempts", "operation_runs"]


def test_failure_requeues_only_until_third_attempt_then_is_terminal() -> None:
    with session() as db:
        repository = OperationRepository(db)
        operation = repository.enqueue(OperationType.FETCH, {})
        for number in range(1, 4):
            lease = repository.lease_next("worker", lease_seconds=60)
            assert lease is not None
            repository.finish_attempt(lease, OperationStatus.FAILED, error_message="Bearer secret")
            if number < 3:
                assert db.get(OperationRunRecord, operation.id).status == OperationStatus.QUEUED  # type: ignore[union-attr]
                record = db.get(OperationRunRecord, operation.id)
                assert record is not None
                record.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
                db.commit()
            else:
                assert db.get(OperationRunRecord, operation.id).status == OperationStatus.FAILED  # type: ignore[union-attr]


def test_retryable_failure_uses_bounded_backoff_and_jitter() -> None:
    with session() as db:
        repository = OperationRepository(db, retry_jitter=lambda bound: bound)
        operation = repository.enqueue(OperationType.FETCH, {})
        lease = repository.lease_next("worker")
        assert lease is not None
        before = datetime.now(UTC)

        assert repository.finish_attempt(lease, OperationStatus.FAILED, retryable=True)

        queued = db.get(OperationRunRecord, operation.id)
        assert queued is not None
        assert queued.status == OperationStatus.QUEUED
        assert queued.next_attempt_at is not None
        # First retry has a one-second exponential base plus one second of jitter.
        scheduled = queued.next_attempt_at.replace(tzinfo=UTC)
        assert scheduled >= before + timedelta(seconds=1.8)
        assert scheduled <= before + timedelta(seconds=2.2)


def test_nonretryable_failure_is_terminal_without_backoff() -> None:
    with session() as db:
        repository = OperationRepository(db)
        operation = repository.enqueue(OperationType.FETCH, {})
        lease = repository.lease_next("worker")
        assert lease is not None

        assert repository.finish_attempt(lease, OperationStatus.FAILED, retryable=False)

        failed = db.get(OperationRunRecord, operation.id)
        assert failed is not None
        assert failed.status == OperationStatus.FAILED
        assert failed.next_attempt_at is not None


def test_cancel_and_terminal_operations_are_immutable() -> None:
    with session() as db:
        repository = OperationRepository(db)
        operation = repository.enqueue(OperationType.FETCH, {})
        assert repository.request_cancel(operation.id)
        assert repository.lease_next("worker") is None
        assert db.get(OperationRunRecord, operation.id).status == OperationStatus.CANCELLED  # type: ignore[union-attr]
        assert not repository.request_cancel(operation.id)
