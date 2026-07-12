from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from newsradar.db.models import (
    FetchRunRecord,
    OperationAttemptRecord,
    OperationEventRecord,
    OperationRunRecord,
    SourceDefinitionRecord,
    WorkerRecord,
)
from newsradar.ingestion.schema import FetchOutcome, FetchResult
from newsradar.ingestion.service import SourceFetchSummary
from newsradar.operations.fetch_runtime import FetchOperationHandler
from newsradar.operations.repository import OperationRepository
from newsradar.operations.worker import Worker
from newsradar.settings import Settings
from newsradar.sources.schema import SourceDefinition
from newsradar.web.app import create_app


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


def _source(source_id: str) -> SourceDefinition:
    return SourceDefinition.model_validate(
        {
            "id": source_id,
            "name": "Web Worker acceptance source",
            "status": "active",
            "nature": "first_party",
            "roles": ["discovery"],
            "language": "en",
            "topics": ["ai"],
            "authority_score": 5,
            "poll_interval_minutes": 60,
            "official_identity_url": "https://acceptance.example.test",
            "access_methods": [
                {"kind": "rss", "url": "https://acceptance.example.test/feed", "priority": 1}
            ],
            "expected_fields": ["title", "canonical_url"],
            "risk": {
                "terms": 0,
                "authentication": 0,
                "stability": 0,
                "data_quality": 0,
                "operating_cost": 0,
            },
            "ingestion": {"enabled": True, "approved_at": "2026-07-12"},
        }
    )


def test_web_enqueue_is_consumed_by_worker_and_visible_in_detail(monkeypatch) -> None:
    engine = _postgres_engine_or_skip()
    suffix = uuid4().hex
    source_id = f"web-worker-{suffix}"
    worker_id = f"web-worker-acceptance-{suffix}"
    operation_id: int | None = None

    @contextmanager
    def session_context() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    try:
        with Session(engine) as setup:
            setup.add(
                SourceDefinitionRecord(
                    id=source_id,
                    name="Web Worker acceptance source",
                    status="active",
                    nature="first_party",
                    language="en",
                    roles=["discovery"],
                    topics=["ai"],
                    authority_score=5,
                    poll_interval_minutes=60,
                    expected_fields=["title", "canonical_url"],
                    definition_hash=suffix,
                )
            )
            setup.commit()

        monkeypatch.setattr("newsradar.web.app.create_session", session_context)
        with TestClient(create_app(), base_url="http://127.0.0.1") as client:
            operations = client.get("/operations")
            token = operations.text.split('name="action_token" value="', 1)[1].split('"', 1)[0]
            queued = client.post(
                "/operations/fetch",
                data={"source_id": source_id, "action_token": token},
                headers={"Origin": "http://127.0.0.1"},
                follow_redirects=False,
            )
            operation_id = int(queued.headers["location"].rsplit("/", 1)[1])

            def execute(source, claimed_operation_id, checkpoint, requested_scope):
                checkpoint("before_acceptance_fetch_run")
                with Session(engine) as fetch_session:
                    run = FetchRunRecord(
                        source_id=source.id,
                        operation_run_id=claimed_operation_id,
                        outcome="succeeded",
                    )
                    fetch_session.add(run)
                    fetch_session.commit()
                    fetch_run_id = run.id
                return SourceFetchSummary(
                    source.id,
                    FetchResult(outcome=FetchOutcome.SUCCEEDED),
                    fetch_run_id=fetch_run_id,
                )

            with Session(engine) as worker_session:
                Worker(OperationRepository(worker_session), worker_id).run_once(
                    FetchOperationHandler([_source(source_id)], execute)
                )

            detail = client.get(f"/operations/{operation_id}")

        assert queued.status_code == 303
        assert "succeeded" in detail.text
        with Session(engine) as verification:
            fetch_run = verification.scalar(
                select(FetchRunRecord).where(
                    FetchRunRecord.operation_run_id == operation_id
                )
            )
            assert fetch_run is not None
    finally:
        with Session(engine) as cleanup:
            if operation_id is not None:
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
                    delete(FetchRunRecord).where(
                        FetchRunRecord.operation_run_id == operation_id
                    )
                )
                cleanup.execute(
                    delete(OperationRunRecord).where(OperationRunRecord.id == operation_id)
                )
            cleanup.execute(delete(WorkerRecord).where(WorkerRecord.worker_id == worker_id))
            cleanup.execute(
                delete(SourceDefinitionRecord).where(SourceDefinitionRecord.id == source_id)
            )
            cleanup.commit()
        engine.dispose()
