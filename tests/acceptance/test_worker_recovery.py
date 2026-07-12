from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    OperationAttemptRecord,
    OperationRunRecord,
    RawItemRecord,
    RawItemSnapshotRecord,
    SourceDefinitionRecord,
    WorkerRecord,
)
from newsradar.operations.repository import OperationLease, OperationRepository
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.operations.worker import Worker


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _source(db: Session) -> None:
    db.add(
        SourceDefinitionRecord(
            id="acceptance-source",
            name="Acceptance source",
            status="active",
            nature="first_party",
            language="en",
            roles=["discovery"],
            topics=["ai"],
            authority_score=5,
            poll_interval_minutes=60,
            expected_fields=["title"],
            definition_hash="acceptance-source-hash",
        )
    )
    db.commit()


def test_expired_worker_lease_is_recovered_without_duplicate_item_or_snapshot() -> None:
    with _session() as db:
        _source(db)
        repository = OperationRepository(db)
        operation = repository.enqueue(OperationType.FETCH, {"source_id": "acceptance-source"})
        first_lease = repository.lease_next("worker-a", lease_seconds=1)

        assert first_lease is not None
        db.add(
            RawItemRecord(
                source_id="acceptance-source",
                external_id="42",
                canonical_url="https://example.test/42",
                payload={},
                content_hash="content-42",
            )
        )
        db.flush()
        item = db.scalar(select(RawItemRecord).where(RawItemRecord.external_id == "42"))
        assert item is not None
        db.add(
            RawItemSnapshotRecord(
                raw_item_id=item.id,
                content_hash="content-42",
                snapshot={"title": "Already committed"},
            )
        )
        record = db.get(OperationRunRecord, operation.id)
        assert record is not None
        record.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

        assert Worker(repository, "worker-b").run_once(
            lambda lease, checkpoint: checkpoint("source")
        )

        recovered = db.get(OperationRunRecord, operation.id)
        assert recovered is not None
        assert recovered.status == OperationStatus.SUCCEEDED
        assert db.scalar(select(RawItemRecord).where(RawItemRecord.external_id == "42")) is not None
        raw_items = db.scalars(
            select(RawItemRecord).where(RawItemRecord.external_id == "42")
        ).all()
        assert len(raw_items) == 1
        assert len(
            db.scalars(
                select(RawItemSnapshotRecord).where(
                    RawItemSnapshotRecord.content_hash == "content-42"
                )
            ).all()
        ) == 1
        attempts = db.scalars(
            select(OperationAttemptRecord).order_by(OperationAttemptRecord.attempt_number)
        ).all()
        assert [attempt.status for attempt in attempts] == [
            OperationStatus.INTERRUPTED,
            OperationStatus.SUCCEEDED,
        ]


def test_only_current_lease_owner_can_finish_an_operation_and_workers_expose_heartbeats() -> None:
    with _session() as db:
        repository = OperationRepository(db)
        operation = repository.enqueue(OperationType.FETCH, {})
        owner = repository.lease_next("worker-a")
        contender = repository.lease_next("worker-b")

        assert owner is not None
        assert contender is None
        owner_record = db.get(WorkerRecord, "worker-a")
        assert owner_record is not None
        assert owner_record.last_heartbeat_at is not None
        assert owner_record.current_operation_run_id == operation.id
        assert not repository.finish_attempt(
            OperationLease(
                owner.operation_id,
                owner.attempt_id,
                owner.attempt_number,
                "worker-b",
                owner.requested_scope,
            ),
            OperationStatus.SUCCEEDED,
        )
        assert repository.finish_attempt(owner, OperationStatus.SUCCEEDED)
        assert db.get(WorkerRecord, "worker-a").current_operation_run_id is None  # type: ignore[union-attr]
