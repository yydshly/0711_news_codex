from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

import newsradar.ingestion.origin_resolver as origin_resolver
from newsradar.ingestion.fetchers.base import FetcherFactory, FetchState, HttpPolicy
from newsradar.ingestion.fetchers.google_news import GoogleNewsFetcher
from newsradar.sources.schema import SourceDefinition

from ...test_source_schema import valid_source


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        origin_resolver.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )


def source(url: str = "https://news.google.com/rss/search?q=ai") -> SourceDefinition:
    data = valid_source()
    data.update({"nature": "aggregator", "roles": ["discovery"], "language": "en"})
    data["access_methods"][0].update({"kind": "rss", "url": url})
    return SourceDefinition.model_validate(data)


def test_factory_selects_google_news_fetcher_for_google_rss() -> None:
    item_source = source()
    async_client = httpx.AsyncClient()
    try:
        assert isinstance(
            FetcherFactory(HttpPolicy(async_client)).for_method(item_source.access_methods[0]),
            GoogleNewsFetcher,
        )
    finally:
        asyncio.run(async_client.aclose())


RSS = (
    b"<rss><channel><item><guid>one</guid><title>Story - Publisher</title>"
    b"<link>https://news.google.com/read/one</link>"
    b"<pubDate>Sat, 11 Jul 2026 12:00:00 GMT</pubDate></item></channel></rss>"
)


@pytest.mark.asyncio
@respx.mock
async def test_google_news_resolves_topic_entry_to_publisher() -> None:
    respx.get("https://news.google.com/rss/topic/technology").mock(
        return_value=httpx.Response(200, content=RSS)
    )
    respx.get("https://news.google.com/read/one").mock(
        return_value=httpx.Response(302, headers={"location": "https://publisher.test/story"})
    )
    respx.get("https://publisher.test/story").mock(return_value=httpx.Response(200))
    item_source = source("https://news.google.com/rss/topic/technology")
    async with httpx.AsyncClient() as client:
        result = await GoogleNewsFetcher(HttpPolicy(client), client).fetch(
            item_source, item_source.access_methods[0], FetchState(), 5
        )

    item = result.items[0]
    assert str(item.discovery_url) == "https://news.google.com/read/one"
    assert str(item.canonical_url) == "https://publisher.test/story"
    assert item.publisher_name == "Publisher"
    assert item.publisher_name != "Google News"


@pytest.mark.asyncio
@respx.mock
async def test_google_news_query_feed_keeps_unresolved_discovery_fallback() -> None:
    respx.get("https://news.google.com/rss/search?q=ai").mock(
        return_value=httpx.Response(200, content=RSS)
    )
    respx.get("https://news.google.com/read/one").mock(return_value=httpx.Response(200))
    item_source = source()
    async with httpx.AsyncClient() as client:
        result = await GoogleNewsFetcher(HttpPolicy(client), client).fetch(
            item_source, item_source.access_methods[0], FetchState(), 5
        )

    item = result.items[0]
    assert str(item.canonical_url) == "https://news.google.com/read/one"
    assert str(item.discovery_url) == "https://news.google.com/read/one"
    assert item.publisher_name is None
    assert item.origin_resolution_status.value == "unresolved"


@pytest.mark.asyncio
@respx.mock
async def test_google_news_strips_sensitive_configured_headers() -> None:
    route = respx.get("https://news.google.com/rss/search?q=ai").mock(
        return_value=httpx.Response(200, content=b"<rss><channel /></rss>")
    )
    item_source = source()
    item_source.access_methods[0].headers.update({"Cookie": "session", "Authorization": "secret"})
    async with httpx.AsyncClient() as client:
        await GoogleNewsFetcher(HttpPolicy(client), client).fetch(
            item_source, item_source.access_methods[0], FetchState(), 5
        )

    assert "cookie" not in route.calls[0].request.headers
    assert "authorization" not in route.calls[0].request.headers
