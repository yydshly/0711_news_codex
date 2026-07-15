from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from newsradar.ingestion.fetchers.base import FetcherFactory, FetchState, HttpPolicy
from newsradar.ingestion.fetchers.techmeme import TechmemeFetcher
from newsradar.sources.schema import SourceDefinition

from ...test_source_schema import valid_source


def source() -> SourceDefinition:
    data = valid_source()
    data.update({"nature": "aggregator", "roles": ["discovery"], "language": "en"})
    data["access_methods"][0].update(
        {"kind": "rss", "url": "https://www.techmeme.com/feed.xml"}
    )
    return SourceDefinition.model_validate(data)


def test_factory_selects_techmeme_fetcher() -> None:
    item_source = source()
    client = httpx.AsyncClient()
    try:
        assert isinstance(
            FetcherFactory(HttpPolicy(client)).for_method(item_source.access_methods[0]),
            TechmemeFetcher,
        )
    finally:
        asyncio.run(client.aclose())


@pytest.mark.asyncio
@respx.mock
async def test_techmeme_extracts_original_story_and_publisher_from_feed_summary() -> None:
    summary = (
        '&lt;a href="https://arstechnica.com/security/context-bombing/"&gt;image&lt;/a&gt;'
        '&lt;p&gt;Dan Goodin / &lt;a href="https://arstechnica.com/"&gt;Ars Technica&lt;/a&gt;:'
        '&lt;b&gt;&lt;a href="https://arstechnica.com/security/context-bombing/"&gt;'
        "Researchers detail context bombing against AI agents&lt;/a&gt;&lt;/b&gt;&lt;/p&gt;"
    )
    rss = (
        "<rss><channel><item><guid>story</guid>"
        "<title>Researchers detail context bombing against AI agents "
        "(Dan Goodin/Ars Technica)</title>"
        "<link>https://www.techmeme.com/260714/p2#a260714p2</link>"
        f"<description>{summary}</description>"
        "<pubDate>Tue, 14 Jul 2026 12:00:00 GMT</pubDate>"
        "</item></channel></rss>"
    ).encode()
    respx.get("https://www.techmeme.com/feed.xml").mock(
        return_value=httpx.Response(200, content=rss)
    )
    item_source = source()
    async with httpx.AsyncClient() as client:
        result = await TechmemeFetcher(HttpPolicy(client)).fetch(
            item_source, item_source.access_methods[0], FetchState(), 5
        )

    item = result.items[0]
    assert item.title == "Researchers detail context bombing against AI agents"
    assert str(item.canonical_url) == "https://arstechnica.com/security/context-bombing/"
    assert str(item.original_url) == "https://www.techmeme.com/260714/p2#a260714p2"
    assert str(item.discovery_url) == "https://www.techmeme.com/260714/p2#a260714p2"
    assert item.publisher_name == "Ars Technica"
    assert str(item.publisher_url) == "https://arstechnica.com/security/context-bombing/"
    assert item.origin_resolution_status.value == "resolved"


@pytest.mark.asyncio
@respx.mock
async def test_techmeme_strips_sensitive_configured_headers() -> None:
    route = respx.get("https://www.techmeme.com/feed.xml").mock(
        return_value=httpx.Response(200, content=b"<rss><channel /></rss>")
    )
    item_source = source()
    item_source.access_methods[0].headers.update(
        {"Cookie": "session", "Authorization": "secret"}
    )
    async with httpx.AsyncClient() as client:
        await TechmemeFetcher(HttpPolicy(client)).fetch(
            item_source, item_source.access_methods[0], FetchState(), 5
        )

    assert "cookie" not in route.calls[0].request.headers
    assert "authorization" not in route.calls[0].request.headers
