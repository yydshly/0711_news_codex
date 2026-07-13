from __future__ import annotations

from datetime import UTC, datetime, timedelta
from contextlib import nullcontext

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

        def execute(source, operation_id, checkpoint, requested_scope):
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

        def execute(source, operation_id, checkpoint, requested_scope):
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


def test_fetch_worker_does_not_retry_credential_or_client_errors() -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler

    with _session() as db:
        operation = OperationRepository(db).enqueue(OperationType.FETCH, {"source_id": "source-a"})

        def execute(source, operation_id, checkpoint, requested_scope):
            return SourceFetchSummary(
                source.id,
                FetchResult(
                    outcome=FetchOutcome.FAILED,
                    http_status=403,
                    error_code="missing_credential",
                    error_message="credential is absent",
                ),
            )

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler([_source()], execute)
        )

        record = db.get(OperationRunRecord, operation.id)
        assert record is not None
        assert record.status == OperationStatus.FAILED
        assert record.attempt_count == 1


def test_fetch_worker_retries_transport_and_rate_limit_failures() -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler

    with _session() as db:
        operation = OperationRepository(db).enqueue(OperationType.FETCH, {"source_id": "source-a"})

        def execute(source, operation_id, checkpoint, requested_scope):
            return SourceFetchSummary(
                source.id,
                FetchResult(
                    outcome=FetchOutcome.FAILED,
                    http_status=429,
                    error_code="rate_limited",
                    retry_after_seconds=15,
                ),
            )

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler([_source()], execute)
        )

        record = db.get(OperationRunRecord, operation.id)
        assert record is not None
        assert record.status == OperationStatus.QUEUED
        assert record.attempt_count == 1


def test_fetch_worker_rejects_expired_operation_before_source_execution() -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler

    with _session() as db:
        expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        operation = OperationRepository(db).enqueue(
            OperationType.FETCH,
            {"source_id": "source-a", "deadline_at": expired},
        )
        calls: list[str] = []

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler([_source()], lambda *_: calls.append("executed"))
        )

        record = db.get(OperationRunRecord, operation.id)
        assert calls == []
        assert record is not None
        assert record.status == OperationStatus.FAILED
        assert record.error_code == "operation_timeout"


def test_fetch_worker_passes_audited_scope_to_executor() -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler

    with _session() as db:
        operation = OperationRepository(db).enqueue(
            OperationType.FETCH,
            {
                "source_id": "source-a",
                "dry_run": True,
                "max_items": 3,
                "one_off": True,
            },
        )
        scopes: list[dict[str, object]] = []

        def execute(source, operation_id, checkpoint, requested_scope):
            scopes.append(dict(requested_scope))
            return SourceFetchSummary(
                source.id,
                FetchResult(outcome=FetchOutcome.SUCCEEDED),
            )

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler([_source()], execute)
        )

        assert scopes == [operation.requested_scope]


def test_trial_fetch_worker_blocks_ineligible_latest_probe_before_creating_fetcher(monkeypatch) -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler
    from newsradar.sources.repository import SourceRepository

    with _session() as db:
        source = _source()
        SourceRepository(db).sync([source])
        operation = OperationRepository(db).enqueue(
            OperationType.FETCH,
            {"source_id": source.id, "trial": True},
        )
        factory_calls: list[object] = []

        def fail_if_fetcher_created(policy):
            factory_calls.append(policy)
            raise AssertionError("trial eligibility must be checked before creating a fetcher")

        monkeypatch.setattr("newsradar.operations.fetch_runtime.create_session", lambda: nullcontext(db))
        monkeypatch.setattr("newsradar.operations.fetch_runtime.FetcherFactory", fail_if_fetcher_created)

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler.production([source])
        )

        record = db.get(OperationRunRecord, operation.id)
        assert factory_calls == []
        assert record is not None
        assert record.status == OperationStatus.PARTIAL
        assert record.error_code == "eligibility_trial_no_probe"
