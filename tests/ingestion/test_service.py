from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from newsradar.db.models import Base, FetchRunRecord, RawItemRecord, SourceFetchStateRecord
from newsradar.ingestion.fetchers.base import FetchState
from newsradar.ingestion.repository import RawItemRepository
from newsradar.ingestion.schema import FetchOutcome, FetchResult
from newsradar.ingestion.service import IngestionService
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
