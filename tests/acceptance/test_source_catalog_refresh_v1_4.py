"""PostgreSQL acceptance boundary for the frozen 187-source catalog wave."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from newsradar.db.models import (
    OperationAttemptRecord,
    OperationEventRecord,
    OperationRunRecord,
    ProviderProbeRunRecord,
    SourceCatalogRefreshMemberRecord,
    SourceProbeRunRecord,
    WorkerRecord,
)
from newsradar.operations.repository import OperationRepository
from newsradar.operations.worker import Worker
from newsradar.providers.probes import ProviderProbeResult
from newsradar.providers.yaml_loader import load_provider_tree
from newsradar.settings import Settings
from newsradar.sources.catalog_refresh import (
    CatalogMemberState,
    CatalogRefreshLane,
    CatalogRefreshMemberSnapshot,
    CatalogRefreshPlan,
)
from newsradar.sources.catalog_refresh_repository import CatalogRefreshRepository
from newsradar.sources.catalog_refresh_runtime import CatalogRefreshHandler
from newsradar.sources.probes.base import ProbeOutcome, ProbeResult
from newsradar.sources.schema import SourceStatus
from newsradar.sources.yaml_loader import load_source_tree
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


async def _content_success(source, method) -> ProbeResult:
    now = datetime.now(UTC)
    return ProbeResult(
        source_id=source.id,
        access_kind=method.kind.value,
        access_url=str(method.url),
        outcome=ProbeOutcome.SUCCESS,
        started_at=now,
        finished_at=now,
        sample_count=1,
        field_completeness=1.0,
        suggested_status=SourceStatus.CANDIDATE,
        reason="acceptance synthetic transport boundary",
    )


async def _capability_success(provider) -> ProviderProbeResult:
    return ProviderProbeResult(
        provider_id=provider.id,
        outcome="success",
        availability=provider.availability.value,
        reason="acceptance capability boundary",
        checked_at=datetime.now(UTC),
        evidence_url=str(provider.docs_url),
    )


def test_postgres_web_wave_worker_reaches_frozen_terminal_detail(monkeypatch) -> None:
    """Web only queues; a real PostgreSQL Worker persists all 187 frozen members."""
    engine = _postgres_engine_or_skip()
    worker_id = f"catalog-refresh-acceptance-{uuid4().hex}"
    operation_id: int | None = None

    @contextmanager
    def session_context() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    try:
        monkeypatch.setattr("newsradar.web.app.create_session", session_context)
        with TestClient(create_app(), base_url="http://127.0.0.1") as client:
            page = client.get("/source-waves")
            token = page.text.split('name="action_token" value="', 1)[1].split('"', 1)[0]
            queued = client.post(
                "/source-waves",
                data={"action_token": token},
                headers={"Origin": "http://127.0.0.1"},
                follow_redirects=False,
            )
            assert queued.status_code == 303
            operation_id = int(queued.headers["location"].rsplit("/", 1)[1])

            handler = CatalogRefreshHandler(
                load_source_tree(Path("sources")),
                load_provider_tree(Path("providers")),
                session_context,
                probe_factory=_content_success,
                provider_probe_factory=_capability_success,
            )
            with Session(engine) as worker_session:
                assert Worker(OperationRepository(worker_session), worker_id).run_once(handler)
            detail = client.get(f"/source-waves/{operation_id}")

        with Session(engine) as verification:
            operation = verification.get(OperationRunRecord, operation_id)
            assert operation is not None
            assert operation.requested_scope["catalog_count"] == 187
            assert operation.progress_current == 187
            assert operation.result_summary["catalog_count"] == 187
            assert operation.result_summary["completed_count"] == 187
            members = verification.scalars(
                select(SourceCatalogRefreshMemberRecord).where(
                    SourceCatalogRefreshMemberRecord.operation_run_id == operation_id
                )
            ).all()
            assert len(members) == 187
            assert sum(
                member.lane in {"content", "capability", "catalog"} for member in members
            ) == 187
            assert all(member.state not in {"pending", "running"} for member in members)
        assert "187" in detail.text
    finally:
        if operation_id is not None:
            with Session(engine) as cleanup:
                cleanup.execute(
                    delete(SourceProbeRunRecord).where(
                        SourceProbeRunRecord.operation_run_id == operation_id
                    )
                )
                cleanup.execute(
                    delete(ProviderProbeRunRecord).where(
                        ProviderProbeRunRecord.operation_run_id == operation_id
                    )
                )
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
                cleanup.execute(delete(WorkerRecord).where(WorkerRecord.worker_id == worker_id))
                cleanup.commit()
        engine.dispose()


def test_postgres_concurrent_terminal_completion_counts_one_member_once() -> None:
    """Separate PostgreSQL sessions contend for one terminal transition safely."""
    engine = _postgres_engine_or_skip()
    operation_id: int | None = None
    try:
        source = load_source_tree(Path("sources"))[0]
        with Session(engine) as setup:
            operation = OperationRunRecord(
                operation_type="source_catalog_refresh",
                trigger="acceptance",
                status="running",
                requested_scope={
                    "catalog_count": 1,
                    "deadline_at": datetime(2100, 1, 1, tzinfo=UTC).isoformat(),
                },
                result_summary={},
                progress_current=0,
                progress_total=1,
                attempt_count=1,
            )
            setup.add(operation)
            setup.flush()
            operation_id = operation.id
            CatalogRefreshRepository(setup).create_members(
                operation_id,
                CatalogRefreshPlan.from_members(
                    [
                        CatalogRefreshMemberSnapshot(
                            source_id=source.id,
                            provider_id=source.provider_id,
                            definition_hash="acceptance",
                            availability="ready",
                            coverage_mode="direct",
                            access_kind="rss",
                            lane=CatalogRefreshLane.CONTENT,
                        )
                    ]
                ),
            )
            setup.commit()

        def finish() -> None:
            with Session(engine) as session:
                CatalogRefreshRepository(session).finish_member(
                    operation_id,
                    source.id,
                    CatalogMemberState.SUCCEEDED,
                    None,
                    "并发验收终态",
                )
                session.commit()

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: finish(), range(2)))

        with Session(engine) as verification:
            operation = verification.get(OperationRunRecord, operation_id)
            assert operation is not None
            assert operation.progress_current == 1
            member = verification.scalar(
                select(SourceCatalogRefreshMemberRecord).where(
                    SourceCatalogRefreshMemberRecord.operation_run_id == operation_id
                )
            )
            assert member is not None
            assert member.state == "succeeded"
    finally:
        if operation_id is not None:
            with Session(engine) as cleanup:
                cleanup.execute(
                    delete(OperationRunRecord).where(OperationRunRecord.id == operation_id)
                )
                cleanup.commit()
        engine.dispose()


def test_postgres_catalog_handler_cancellation_stops_after_current_probe() -> None:
    """A cancellation observed at a handler checkpoint leaves its member resumable."""
    engine = _postgres_engine_or_skip()
    operation_id: int | None = None
    calls = 0
    try:
        source = load_source_tree(Path("sources"))[0]
        handler = CatalogRefreshHandler([source], [], lambda: Session(engine))
        with Session(engine) as setup:
            operation = OperationRunRecord(
                operation_type="source_catalog_refresh",
                trigger="acceptance",
                status="queued",
                requested_scope={
                    "catalog_count": 1,
                    "deadline_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                },
                result_summary={},
                progress_total=1,
                attempt_count=0,
            )
            setup.add(operation)
            setup.flush()
            operation_id = operation.id
            CatalogRefreshRepository(setup).create_members(
                operation_id,
                CatalogRefreshPlan.from_members(
                    [
                        CatalogRefreshMemberSnapshot(
                            source_id=source.id,
                            provider_id=source.provider_id,
                            definition_hash=handler.definition_hash(source, []),
                            availability="ready",
                            coverage_mode="direct",
                            access_kind=source.access_methods[0].kind.value,
                            lane=CatalogRefreshLane.CONTENT,
                        )
                    ]
                ),
            )
            setup.commit()

        async def cancel_after_first_probe(source, method) -> ProbeResult:
            nonlocal calls
            calls += 1
            with Session(engine) as session:
                assert OperationRepository(session).request_cancel(operation_id)
            return await _content_success(source, method)

        handler = CatalogRefreshHandler(
            [source], [], lambda: Session(engine), cancel_after_first_probe
        )
        with Session(engine) as worker_session:
            worker = Worker(OperationRepository(worker_session), "cancel-acceptance")
            assert not worker.run_once(handler)
        with Session(engine) as verification:
            operation = verification.get(OperationRunRecord, operation_id)
            member = verification.scalar(
                select(SourceCatalogRefreshMemberRecord).where(
                    SourceCatalogRefreshMemberRecord.operation_run_id == operation_id
                )
            )
            assert operation is not None and operation.status == "cancelled"
            assert member is not None and member.state == "running"
        assert calls == 1
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
                cleanup.execute(
                    delete(WorkerRecord).where(WorkerRecord.worker_id == "cancel-acceptance")
                )
                cleanup.commit()
        engine.dispose()
