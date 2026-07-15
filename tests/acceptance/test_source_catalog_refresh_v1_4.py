"""PostgreSQL acceptance boundary for the frozen 187-source catalog wave."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
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
from newsradar.providers.repository import canonical_provider
from newsradar.providers.yaml_loader import load_provider_tree
from newsradar.settings import Settings
from newsradar.sources.catalog_refresh import (
    CatalogMemberState,
    CatalogRefreshLane,
    CatalogRefreshMemberSnapshot,
    CatalogRefreshPlan,
    CatalogResultCode,
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


def _frozen_content_member(source, providers) -> CatalogRefreshMemberSnapshot:
    provider = next(item for item in providers if item.id == source.provider_id)
    return CatalogRefreshMemberSnapshot(
        source_id=source.id,
        provider_id=source.provider_id,
        definition_hash=CatalogRefreshHandler.definition_hash(source, providers),
        provider_definition_hash=canonical_provider(provider)[1],
        availability=source.availability.value,
        coverage_mode=source.coverage_mode.value,
        access_kind=source.access_methods[0].kind.value,
        lane=CatalogRefreshLane.CONTENT,
    )


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
            assert (
                sum(member.lane in {"content", "capability", "catalog"} for member in members)
                == 187
            )
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
        source, other_source = load_source_tree(Path("sources"))[:2]
        providers = load_provider_tree(Path("providers"))
        with Session(engine) as setup:
            operation = OperationRunRecord(
                operation_type="source_catalog_refresh",
                trigger="acceptance",
                status="running",
                requested_scope={
                    "catalog_count": 2,
                    "deadline_at": datetime(2100, 1, 1, tzinfo=UTC).isoformat(),
                },
                result_summary={},
                progress_current=0,
                progress_total=2,
                attempt_count=1,
            )
            setup.add(operation)
            setup.flush()
            operation_id = operation.id
            CatalogRefreshRepository(setup).create_members(
                operation_id,
                CatalogRefreshPlan.from_members(
                    [
                        _frozen_content_member(source, providers),
                        _frozen_content_member(other_source, providers),
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
                    SourceCatalogRefreshMemberRecord.operation_run_id == operation_id,
                    SourceCatalogRefreshMemberRecord.source_id == source.id,
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
        providers = load_provider_tree(Path("providers"))
        handler = CatalogRefreshHandler([source], providers, lambda: Session(engine))
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
                CatalogRefreshPlan.from_members([_frozen_content_member(source, providers)]),
            )
            setup.commit()

        async def cancel_after_first_probe(source, method) -> ProbeResult:
            nonlocal calls
            calls += 1
            with Session(engine) as session:
                assert OperationRepository(session).request_cancel(operation_id)
            return await _content_success(source, method)

        handler = CatalogRefreshHandler(
            [source], providers, lambda: Session(engine), cancel_after_first_probe
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


def test_postgres_expired_lease_does_not_reprobe_an_abandoned_running_member() -> None:
    """A recovered lease leaves an in-flight member fenced until its claimant finishes."""
    engine = _postgres_engine_or_skip()
    operation_id: int | None = None
    worker_id = "catalog-recovery-acceptance"
    calls: list[str] = []
    try:
        sources = load_source_tree(Path("sources"))[:3]
        providers = load_provider_tree(Path("providers"))
        handler = CatalogRefreshHandler(sources, providers, lambda: Session(engine))
        with Session(engine) as setup:
            operation = OperationRunRecord(
                operation_type="source_catalog_refresh",
                trigger="acceptance",
                status="running",
                requested_scope={
                    "catalog_count": 3,
                    "deadline_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                },
                result_summary={},
                progress_total=3,
                attempt_count=1,
                lease_expires_at=datetime(2000, 1, 1, tzinfo=UTC),
            )
            setup.add(operation)
            setup.flush()
            operation_id = operation.id
            snapshots = [_frozen_content_member(source, providers) for source in sources]
            repository = CatalogRefreshRepository(setup)
            repository.create_members(operation_id, CatalogRefreshPlan.from_members(snapshots))
            prior = SourceProbeRunRecord(
                operation_run_id=operation_id,
                source_id=sources[0].id,
                access_kind=sources[0].access_methods[0].kind.value,
                access_url=str(sources[0].access_methods[0].url),
                outcome="succeeded",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                response_headers={},
                metrics={},
                suggested_status="candidate",
                reason="prior success",
            )
            setup.add(prior)
            setup.flush()
            repository.finish_member(
                operation_id,
                sources[0].id,
                CatalogMemberState.SUCCEEDED,
                None,
                "prior success",
                content_probe_run_ids=[prior.id],
            )
            repository.start_member(operation_id, sources[1].id)
            repository.finish_member(
                operation_id,
                sources[2].id,
                CatalogMemberState.DEGRADED,
                CatalogResultCode.NO_CONTENT,
                "prior degraded",
            )
            setup.commit()

        async def probe(source, method) -> ProbeResult:
            calls.append(source.id)
            return await _content_success(source, method)

        handler = CatalogRefreshHandler(sources, providers, lambda: Session(engine), probe)
        with Session(engine) as worker_session:
            assert Worker(OperationRepository(worker_session), worker_id).run_once(handler)
        with Session(engine) as verification:
            operation = verification.get(OperationRunRecord, operation_id)
            assert operation is not None
            assert operation.status == "partial"
            assert operation.result_summary["catalog_count"] == 3
            assert operation.result_summary["completed_count"] == 2
            assert operation.result_summary["degraded"] == 1
            assert operation.result_summary["recovery_note"] == (
                "存在尚未安全完成的成员认领，本次未重复探测；等待原认领完成，"
                "或在确认其已停止后新建批次重试。"
            )
            successful_probes = verification.scalars(
                select(SourceProbeRunRecord).where(
                    SourceProbeRunRecord.operation_run_id == operation_id,
                    SourceProbeRunRecord.source_id == sources[0].id,
                )
            ).all()
            assert len(successful_probes) == 1
        assert calls == []
    finally:
        if operation_id is not None:
            with Session(engine) as cleanup:
                cleanup.execute(
                    delete(SourceProbeRunRecord).where(
                        SourceProbeRunRecord.operation_run_id == operation_id
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


def test_postgres_recovered_lease_never_duplicates_a_blocked_inflight_probe() -> None:
    """A replacement Worker observes the old attempt's fence and performs no second probe."""
    engine = _postgres_engine_or_skip()
    operation_id: int | None = None
    started, release = Event(), Event()
    calls = 0
    old_thread: Thread | None = None
    try:
        source = load_source_tree(Path("sources"))[0]
        providers = load_provider_tree(Path("providers"))
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
                CatalogRefreshPlan.from_members([_frozen_content_member(source, providers)]),
            )
            setup.commit()

        async def blocked_probe(source, method) -> ProbeResult:
            nonlocal calls
            calls += 1
            started.set()
            assert release.wait(10)
            return await _content_success(source, method)

        old_handler = CatalogRefreshHandler(
            [source], providers, lambda: Session(engine), blocked_probe
        )

        def run_old_worker() -> None:
            with Session(engine) as session:
                Worker(OperationRepository(session), "catalog-old-claim").run_once(old_handler)

        old_thread = Thread(target=run_old_worker)
        old_thread.start()
        assert started.wait(10)
        with Session(engine) as session:
            operation = session.get(OperationRunRecord, operation_id)
            assert operation is not None
            operation.lease_expires_at = datetime(2000, 1, 1, tzinfo=UTC)
            session.commit()

        async def unexpected_probe(source, method) -> ProbeResult:
            nonlocal calls
            calls += 1
            return await _content_success(source, method)

        new_handler = CatalogRefreshHandler(
            [source], providers, lambda: Session(engine), unexpected_probe
        )
        with Session(engine) as session:
            assert Worker(OperationRepository(session), "catalog-new-claim").run_once(new_handler)
        assert calls == 1
    finally:
        release.set()
        if old_thread is not None:
            old_thread.join(10)
        if operation_id is not None:
            with Session(engine) as cleanup:
                cleanup.execute(
                    delete(SourceProbeRunRecord).where(
                        SourceProbeRunRecord.operation_run_id == operation_id
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
                cleanup.execute(
                    delete(WorkerRecord).where(
                        WorkerRecord.worker_id.in_(["catalog-old-claim", "catalog-new-claim"])
                    )
                )
                cleanup.commit()
        engine.dispose()


def test_postgres_recovered_lease_never_duplicates_a_blocked_provider_probe() -> None:
    """Capability groups are claim-fenced before ProviderProbe reaches the network boundary."""
    engine = _postgres_engine_or_skip()
    operation_id: int | None = None
    started, release = Event(), Event()
    calls = 0
    old_thread: Thread | None = None
    try:
        sources = load_source_tree(Path("sources"))[:2]
        providers = load_provider_tree(Path("providers"))
        provider = next(item for item in providers if item.id == sources[0].provider_id)
        sources = [source.model_copy(update={"provider_id": provider.id}) for source in sources]
        snapshots = [
            CatalogRefreshMemberSnapshot(
                source_id=source.id,
                provider_id=provider.id,
                definition_hash=CatalogRefreshHandler.definition_hash(source, [provider]),
                provider_definition_hash=canonical_provider(provider)[1],
                availability="requires_credentials",
                coverage_mode=source.coverage_mode.value,
                access_kind="public_api",
                lane=CatalogRefreshLane.CAPABILITY,
            )
            for source in sources
        ]
        with Session(engine) as setup:
            operation = OperationRunRecord(
                operation_type="source_catalog_refresh",
                trigger="acceptance",
                status="queued",
                requested_scope={
                    "catalog_count": 2,
                    "deadline_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                },
                result_summary={},
                progress_total=2,
                attempt_count=0,
            )
            setup.add(operation)
            setup.flush()
            operation_id = operation.id
            CatalogRefreshRepository(setup).create_members(
                operation_id, CatalogRefreshPlan.from_members(snapshots)
            )
            setup.commit()

        async def blocked_provider_probe(candidate) -> ProviderProbeResult:
            nonlocal calls
            calls += 1
            started.set()
            assert release.wait(10)
            return await _capability_success(candidate)

        old_handler = CatalogRefreshHandler(
            sources,
            [provider],
            lambda: Session(engine),
            provider_probe_factory=blocked_provider_probe,
        )

        def run_old_worker() -> None:
            with Session(engine) as session:
                Worker(OperationRepository(session), "catalog-provider-old-claim").run_once(
                    old_handler
                )

        old_thread = Thread(target=run_old_worker)
        old_thread.start()
        assert started.wait(10)
        with Session(engine) as session:
            operation = session.get(OperationRunRecord, operation_id)
            assert operation is not None
            operation.lease_expires_at = datetime(2000, 1, 1, tzinfo=UTC)
            session.commit()

        async def unexpected_provider_probe(candidate) -> ProviderProbeResult:
            nonlocal calls
            calls += 1
            return await _capability_success(candidate)

        new_handler = CatalogRefreshHandler(
            sources,
            [provider],
            lambda: Session(engine),
            provider_probe_factory=unexpected_provider_probe,
        )
        with Session(engine) as session:
            assert Worker(OperationRepository(session), "catalog-provider-new-claim").run_once(
                new_handler
            )
        assert calls == 1
    finally:
        release.set()
        if old_thread is not None:
            old_thread.join(10)
        if operation_id is not None:
            with Session(engine) as cleanup:
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
                cleanup.execute(
                    delete(WorkerRecord).where(
                        WorkerRecord.worker_id.in_(
                            ["catalog-provider-old-claim", "catalog-provider-new-claim"]
                        )
                    )
                )
                cleanup.commit()
        engine.dispose()
