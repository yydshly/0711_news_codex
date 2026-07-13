from __future__ import annotations

from datetime import UTC, datetime

import pytest
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
            "trial": False,
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


def test_retry_rejects_durable_nonretryable_failure() -> None:
    with session() as db:
        original = OperationRunRecord(
            operation_type="event_recluster",
            trigger="web",
            status="failed",
            requested_scope={"event_id": 1, "actor": "web"},
            result_summary={},
            attempt_count=1,
            error_code="unsupported_action",
        )
        db.add(original)
        db.commit()

        with pytest.raises(ValueError, match="not retryable"):
            OperationCommandService(db).retry(original.id, trigger="web")


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


def test_enqueue_event_pipeline_uses_window_versions_and_idempotency_key() -> None:
    now = datetime(2026, 7, 12, 0, 0, tzinfo=UTC)
    with session() as db:
        operation_id = OperationCommandService(db, utcnow=lambda: now).enqueue_event_pipeline(
            window_hours=24, trigger="cli"
        )
        record = db.get(OperationRunRecord, operation_id)

        assert record is not None
        assert record.operation_type == "event_pipeline"
        assert record.requested_scope["window_hours"] == 24
        assert record.requested_scope["algorithm_versions"]
        assert record.requested_scope["idempotency_key"]
