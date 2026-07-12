from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from newsradar.db.models import Base, RawItemRecord, SourceFetchStateRecord
from newsradar.ingestion.fetchers.base import FetchState
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
        data["ingestion"] = {"enabled": True}
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
        data["ingestion"] = {"enabled": True}
        source = SourceDefinition.model_validate(data)
        SourceRepository(session).sync([source])
        session.commit()

        summary = await IngestionService(session, ItemFactory()).fetch_source(source, dry_run=True)

        assert summary.result.outcome is FetchOutcome.SUCCEEDED
        assert session.scalar(select(func.count()).select_from(RawItemRecord)) == 0
        assert session.scalar(select(func.count()).select_from(SourceFetchStateRecord)) == 0
