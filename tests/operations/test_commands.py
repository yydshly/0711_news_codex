from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import Base, OperationRunRecord
from newsradar.operations.commands import OperationCommandService
from newsradar.settings import Settings


def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_enqueue_fetch_records_complete_scope() -> None:
    with session() as db:
        operation_id = OperationCommandService(db).enqueue_fetch(
            source_id="github-openai-python",
            provider=None,
            dry_run=False,
            max_items=5,
            one_off=False,
            trigger="cli",
        )

        record = db.get(OperationRunRecord, operation_id)

        assert record is not None
        assert record.status == "queued"
        assert record.trigger == "cli"
        scope = dict(record.requested_scope)
        assert datetime.fromisoformat(scope.pop("deadline_at")).tzinfo is not None
        assert scope == {
            "source_id": "github-openai-python",
            "provider": None,
            "dry_run": False,
            "max_items": 5,
            "one_off": False,
        }


def test_retry_creates_new_auditable_operation() -> None:
    with session() as db:
        service = OperationCommandService(db)
        original_id = service.enqueue_fetch(source_id="github-openai-python", trigger="web")
        original = db.get(OperationRunRecord, original_id)
        assert original is not None
        original.status = "succeeded"
        db.commit()

        retry_id = service.retry(original_id, trigger="web")
        retry = db.get(OperationRunRecord, retry_id)

        assert retry is not None
        assert retry.id != original_id
        assert retry.trigger == "web"
        assert retry.requested_scope["retry_of_operation_id"] == original_id


def test_enqueue_fetch_persists_operation_deadline() -> None:
    now = datetime(2026, 7, 12, 0, 0, tzinfo=UTC)
    with session() as db:
        service = OperationCommandService(
            db,
            settings=Settings(operation_timeout_seconds=30),
            utcnow=lambda: now,
        )

        operation_id = service.enqueue_fetch(source_id="source", trigger="cli")
        record = db.get(OperationRunRecord, operation_id)

        assert record is not None
        assert record.requested_scope["deadline_at"] == "2026-07-12T00:00:30+00:00"
