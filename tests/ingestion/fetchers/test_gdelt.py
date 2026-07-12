from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from newsradar.ingestion.fetchers.base import FetcherFactory, FetchState, HttpPolicy
from newsradar.ingestion.fetchers.gdelt import GdeltFetcher
from newsradar.ingestion.schema import FetchOutcome
from newsradar.sources.schema import SourceDefinition

from ...test_source_schema import valid_source


def source(query: str = "artificial intelligence") -> SourceDefinition:
    data = valid_source()
    data.update({"nature": "aggregator", "roles": ["discovery"], "language": "en"})
    data["access_methods"][0].update(
        {
            "kind": "public_api",
            "url": "https://api.gdeltproject.org/api/v2/doc/doc",
            "params": {"query": query},
        }
    )
    return SourceDefinition.model_validate(data)


def test_factory_selects_gdelt_fetcher_for_gdelt_api() -> None:
    item_source = source()
    async_client = httpx.AsyncClient()
    try:
        assert isinstance(
            FetcherFactory(HttpPolicy(async_client)).for_method(item_source.access_methods[0]),
            GdeltFetcher,
        )
    finally:
        asyncio.run(async_client.aclose())


@pytest.mark.asyncio
@respx.mock
async def test_gdelt_uses_url_derived_stable_identity_across_queries() -> None:
    route = respx.get("https://api.gdeltproject.org/api/v2/doc/doc").mock(
        return_value=httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "url": "https://publisher.test/story",
                        "title": "Story",
                        "domain": "publisher.test",
                        "language": "English",
                        "seendate": "20260711T120000Z",
                    }
                ]
            },
        )
    )
    async with httpx.AsyncClient() as client:
        fetcher = GdeltFetcher(HttpPolicy(client))
        first = await fetcher.fetch(source("ai"), source("ai").access_methods[0], FetchState(), 5)
        second = await fetcher.fetch(
            source("agents"), source("agents").access_methods[0], FetchState(), 5
        )

    assert first.outcome is FetchOutcome.SUCCEEDED
    assert first.items[0].external_id == second.items[0].external_id
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_gdelt_keeps_discovery_only_attribution_and_isolates_ambiguous_records() -> None:
    respx.get("https://api.gdeltproject.org/api/v2/doc/doc").mock(
        return_value=httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "url": "https://publisher.test/story",
                        "title": "Story",
                        "domain": "publisher.test",
                        "language": "French",
                        "seendate": "20260711T120000Z",
                    },
                    {
                        "url": "https://publisher.test/unknown",
                        "title": "Unknown",
                        "domain": "publisher.test, other.test",
                    },
                ]
            },
        )
    )
    item_source = source()
    async with httpx.AsyncClient() as client:
        result = await GdeltFetcher(HttpPolicy(client)).fetch(
            item_source, item_source.access_methods[0], FetchState(), 5
        )

    first, second = result.items
    assert first.publisher_name == "Publisher"
    assert first.language == "fr"
    assert first.published_at is not None
    assert str(first.discovery_url) == "https://publisher.test/story"
    assert second.publisher_name is None
    assert second.origin_resolution_status.value == "unresolved"
