from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import Base, OperationRunRecord
from newsradar.ingestion.schema import FetchOutcome, FetchResult
from newsradar.ingestion.service import SourceFetchSummary
from newsradar.operations.repository import OperationRepository
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.operations.worker import Worker
from newsradar.sources.schema import SourceDefinition


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _source(source_id: str = "source-a") -> SourceDefinition:
    return SourceDefinition.model_validate(
        {
            "id": source_id,
            "name": "Source A",
            "status": "active",
            "nature": "first_party",
            "roles": ["discovery"],
            "language": "en",
            "topics": ["ai"],
            "authority_score": 5,
            "poll_interval_minutes": 60,
            "official_identity_url": "https://source-a.test",
            "access_methods": [
                {"kind": "rss", "url": "https://source-a.test/feed", "priority": 1}
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


def test_worker_executes_queued_fetch_and_persists_summary() -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler

    with _session() as db:
        operation = OperationRepository(db).enqueue(OperationType.FETCH, {"source_id": "source-a"})
        calls: list[str] = []

        def execute(source, operation_id, checkpoint):
            calls.append(source.id)
            assert operation_id == operation.id
            checkpoint("network_complete")
            return SourceFetchSummary(
                source.id,
                FetchResult(outcome=FetchOutcome.SUCCEEDED, items_received=2, items_inserted=1),
                fetch_run_id=9,
            )

        processed = Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler([_source()], execute)
        )

        record = db.get(OperationRunRecord, operation.id)
        assert processed is True
        assert calls == ["source-a"]
        assert record is not None
        assert record.status == OperationStatus.SUCCEEDED
        assert record.result_summary == {
            "source_id": "source-a",
            "fetch_run_id": 9,
            "outcome": "succeeded",
            "items_received": 2,
            "items_inserted": 1,
        }


def test_worker_keeps_policy_blocked_fetch_terminal_without_retry() -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler

    with _session() as db:
        operation = OperationRepository(db).enqueue(OperationType.FETCH, {"source_id": "source-a"})

        def execute(source, operation_id, checkpoint):
            return SourceFetchSummary(
                source.id,
                FetchResult(
                    outcome=FetchOutcome.BLOCKED,
                    error_code="missing_credentials",
                    error_message="Credentials are not configured",
                ),
            )

        processed = Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler([_source()], execute)
        )

        record = db.get(OperationRunRecord, operation.id)
        assert processed is True
        assert record is not None
        assert record.status == OperationStatus.PARTIAL
        assert record.attempt_count == 1
        assert record.error_code == "missing_credentials"


def test_worker_marks_unknown_fetch_source_failed_without_retry() -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler

    with _session() as db:
        operation = OperationRepository(db).enqueue(OperationType.FETCH, {"source_id": "missing"})

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler([], lambda *_: None)
        )

        record = db.get(OperationRunRecord, operation.id)
        assert record is not None
        assert record.status == OperationStatus.FAILED
        assert record.attempt_count == 1
        assert record.error_code == "unknown_source"
