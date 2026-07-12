from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from newsradar.db.models import Base, FetchRunRecord, RawItemRecord, SourceFetchStateRecord
from newsradar.ingestion.fetchers.base import FetchState
from newsradar.ingestion.repository import RawItemRepository
from newsradar.ingestion.schema import FetchOutcome, FetchResult
from newsradar.ingestion.service import IngestionService
from newsradar.settings import Settings
from newsradar.sources.repository import SourceRepository
from newsradar.sources.schema import SourceDefinition

from ..test_source_schema import valid_source


class InspectingFetcher:
    def __init__(self, session: Session):
        self.session = session

    async def fetch(self, source, method, state: FetchState, limit: int) -> FetchResult:
        assert not self.session.in_transaction()
        return FetchResult(outcome=FetchOutcome.NO_CHANGE)


class InspectingFactory:
    def __init__(self, session: Session):
        self.fetcher = InspectingFetcher(session)

    def for_method(self, method):
        return self.fetcher


class ItemFetcher:
    async def fetch(self, source, method, state: FetchState, limit: int) -> FetchResult:
        from newsradar.ingestion.schema import NormalizedRawItem

        return FetchResult(
            outcome=FetchOutcome.SUCCEEDED,
            items=(
                NormalizedRawItem(
                    external_id="fixture",
                    title="Fixture",
                    canonical_url="https://fixture.test/item",
                    raw_payload={},
                ),
            ),
        )


class ItemFactory:
    def for_method(self, method):
        return ItemFetcher()


class FailedFetcher:
    async def fetch(self, source, method, state: FetchState, limit: int) -> FetchResult:
        return FetchResult(
            outcome=FetchOutcome.FAILED,
            error_code="upstream_timeout",
            error_message="upstream timed out",
        )


class FailedFactory:
    def for_method(self, method):
        return FailedFetcher()


class SlowFetcher:
    async def fetch(self, source, method, state: FetchState, limit: int) -> FetchResult:
        await asyncio.sleep(60)
        raise AssertionError("source timeout did not cancel the fetch")


class SlowFactory:
    def for_method(self, method):
        return SlowFetcher()


class SecretFailureFetcher:
    async def fetch(self, source, method, state: FetchState, limit: int) -> FetchResult:
        raise RuntimeError("request failed: https://api.test/items?key=super-secret-value")


class SecretFailureFactory:
    def for_method(self, method):
        return SecretFailureFetcher()


@pytest.mark.asyncio
async def test_service_closes_state_read_transaction_before_network_fetch() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        data = valid_source()
        data["ingestion"] = {"enabled": True, "approved_at": "2026-07-11"}
        source = SourceDefinition.model_validate(data)
        SourceRepository(session).sync([source])
        session.commit()

        summary = await IngestionService(session, InspectingFactory(session)).fetch_source(source)

    assert summary.result.outcome is FetchOutcome.NO_CHANGE


@pytest.mark.asyncio
async def test_no_change_is_healthy_and_resets_failure_streak() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        data = valid_source()
        data["ingestion"] = {"enabled": True, "approved_at": "2026-07-11"}
        source = SourceDefinition.model_validate(data)
        SourceRepository(session).sync([source])
        session.commit()

        await IngestionService(session, InspectingFactory(session)).fetch_source(source)
        state = session.scalar(select(SourceFetchStateRecord))

        assert state is not None
        assert state.consecutive_failures == 0
        assert state.last_error_code is None


@pytest.mark.asyncio
async def test_service_dry_run_writes_neither_raw_items_nor_cursor_state() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        data = valid_source()
        data["ingestion"] = {"enabled": True, "approved_at": "2026-07-11"}
        source = SourceDefinition.model_validate(data)
        SourceRepository(session).sync([source])
        session.commit()

        summary = await IngestionService(session, ItemFactory()).fetch_source(source, dry_run=True)

        assert summary.result.outcome is FetchOutcome.SUCCEEDED
        assert session.scalar(select(func.count()).select_from(RawItemRecord)) == 0
        assert session.scalar(select(func.count()).select_from(SourceFetchStateRecord)) == 0


def test_postgres_advisory_lock_uses_one_dedicated_connection_for_lock_and_unlock() -> None:
    events: list[str] = []

    class Connection:
        def scalar(self, statement):
            events.append("unlock" if "pg_advisory_unlock" in str(statement) else "lock")
            return True

        def rollback(self):
            events.append("rollback")

        def close(self):
            events.append("close")

    class Bind:
        class dialect:
            name = "postgresql"

        def connect(self):
            events.append("connect")
            return connection

    connection = Connection()
    service = object.__new__(IngestionService)
    service.session = type("Session", (), {"bind": Bind()})()

    locked = service._acquire_advisory_lock("source")
    service._release_advisory_lock(locked, "source")

    assert events == ["connect", "lock", "rollback", "unlock", "rollback", "close"]


@pytest.mark.asyncio
async def test_lock_is_released_when_persistence_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        data = valid_source()
        data["ingestion"] = {"enabled": True, "approved_at": "2026-07-11"}
        source = SourceDefinition.model_validate(data)
        SourceRepository(session).sync([source])
        session.commit()
        service = IngestionService(session, ItemFactory())
        sentinel = object()
        released: list[object] = []
        monkeypatch.setattr(service, "_acquire_advisory_lock", lambda source_id: sentinel)
        monkeypatch.setattr(
            service,
            "_release_advisory_lock",
            lambda connection, source_id: released.append(connection),
        )
        monkeypatch.setattr(
            service, "_start_run", lambda *args: (_ for _ in ()).throw(RuntimeError("db"))
        )

        with pytest.raises(RuntimeError, match="db"):
            await service.fetch_source(source)

    assert released == [sentinel]


@pytest.mark.asyncio
async def test_service_records_item_write_failure_and_finishes_fetch_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        data = valid_source()
        data["ingestion"] = {"enabled": True, "approved_at": "2026-07-11"}
        source = SourceDefinition.model_validate(data)
        SourceRepository(session).sync([source])
        session.commit()

        def fail_write(*args, **kwargs):
            raise RuntimeError("item too large")

        monkeypatch.setattr(RawItemRepository, "upsert", fail_write)
        summary = await IngestionService(session, ItemFactory()).fetch_source(source)

        assert summary.result.outcome is FetchOutcome.PARTIAL
        assert summary.result.items_failed == 1
        assert session.scalar(select(FetchRunRecord.outcome)) == FetchOutcome.PARTIAL.value


@pytest.mark.asyncio
async def test_failed_fetch_increments_source_failure_state() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        data = valid_source()
        data["ingestion"] = {"enabled": True, "approved_at": "2026-07-11"}
        source = SourceDefinition.model_validate(data)
        SourceRepository(session).sync([source])
        session.commit()

        summary = await IngestionService(session, FailedFactory()).fetch_source(source)
        state = session.scalar(select(SourceFetchStateRecord))

        assert summary.result.outcome is FetchOutcome.FAILED
        assert state is not None
        assert state.consecutive_failures == 1
        assert state.last_failure_at is not None
        assert state.last_error_code == "upstream_timeout"


@pytest.mark.asyncio
async def test_source_timeout_returns_retryable_transport_failure() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        data = valid_source()
        data["ingestion"] = {"enabled": True, "approved_at": "2026-07-11"}
        source = SourceDefinition.model_validate(data)
        SourceRepository(session).sync([source])
        session.commit()

        summary = await IngestionService(
            session,
            SlowFactory(),
            settings=Settings(source_timeout_seconds=0.01),
        ).fetch_source(source)

        assert summary.result.outcome is FetchOutcome.FAILED
        assert summary.result.error_code == "source_timeout"
        assert summary.result.error_category.value == "transport"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_fetch_failure_is_redacted_before_database_persistence() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        data = valid_source()
        data["ingestion"] = {"enabled": True, "approved_at": "2026-07-11"}
        source = SourceDefinition.model_validate(data)
        SourceRepository(session).sync([source])
        session.commit()

        await IngestionService(session, SecretFailureFactory()).fetch_source(source)
        error_message = session.scalar(select(FetchRunRecord.error_message))

        assert error_message is not None
        assert "super-secret-value" not in error_message
        assert "[REDACTED]" in error_message


@pytest.mark.asyncio
async def test_injected_settings_determine_configured_credentials() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        data = valid_source()
        data["ingestion"] = {"enabled": True, "approved_at": "2026-07-11"}
        data["access_methods"][0]["auth_envs"] = ["YOUTUBE_API_KEY"]
        source = SourceDefinition.model_validate(data)
        SourceRepository(session).sync([source])
        session.commit()

        summary = await IngestionService(
            session,
            InspectingFactory(session),
            settings=Settings(youtube_api_key="configured"),
        ).fetch_source(source)

        assert summary.result.outcome is FetchOutcome.NO_CHANGE
