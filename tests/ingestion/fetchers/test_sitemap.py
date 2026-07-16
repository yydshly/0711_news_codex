from datetime import UTC, datetime

import httpx
import pytest
import respx

from newsradar.ingestion.fetchers.base import FetcherFactory, FetchState, HttpPolicy
from newsradar.ingestion.schema import FetchOutcome
from newsradar.sources.schema import SourceDefinition

from ...test_source_schema import valid_source


def source() -> SourceDefinition:
    data = valid_source()
    data["access_methods"][0].update(
        {"kind": "sitemap", "url": "https://site.test/sitemap.xml"}
    )
    return SourceDefinition.model_validate(data)


@pytest.mark.asyncio
@respx.mock
async def test_sitemap_normalizes_news_title_and_slug_fallback() -> None:
    from newsradar.ingestion.fetchers.sitemap import SitemapFetcher

    respx.get("https://site.test/sitemap.xml").mock(
        return_value=httpx.Response(
            200,
            content=b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://site.test/posts/official-story?utm_source=feed#top</loc>
    <lastmod>2026-07-15T08:00:00Z</lastmod>
    <news:news>
      <news:publication_date>2026-07-14T07:00:00Z</news:publication_date>
      <news:title>Official News Title</news:title>
    </news:news>
  </url>
  <url>
    <loc>https://site.test/p/openai-launches-new-model</loc>
    <lastmod>2026-07-13</lastmod>
  </url>
</urlset>""",
        )
    )

    async with httpx.AsyncClient() as client:
        result = await SitemapFetcher(HttpPolicy(client)).fetch(
            source(), source().access_methods[0], FetchState(), 10
        )

    assert result.outcome is FetchOutcome.SUCCEEDED
    assert [item.title for item in result.items] == [
        "Official News Title",
        "Openai Launches New Model",
    ]
    assert str(result.items[0].canonical_url) == "https://site.test/posts/official-story"
    assert result.items[0].published_at == datetime(2026, 7, 14, 7, tzinfo=UTC)
    assert result.items[0].source_updated_at == datetime(2026, 7, 15, 8, tzinfo=UTC)
    assert result.items[1].published_at == datetime(2026, 7, 13, tzinfo=UTC)
    assert result.items[0].raw_payload["title_source"] == "news_sitemap"
    assert result.items[1].raw_payload["title_source"] == "url_slug"
    assert all(item.summary is None and item.content is None for item in result.items)


@pytest.mark.asyncio
@respx.mock
async def test_sitemap_isolates_malformed_entry_and_honors_limit() -> None:
    from newsradar.ingestion.fetchers.sitemap import SitemapFetcher

    respx.get("https://site.test/sitemap.xml").mock(
        return_value=httpx.Response(
            200,
            content=b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://user:secret@site.test/private</loc></url>
  <url><loc>https://site.test/p/good-one</loc><lastmod>not-a-date</lastmod></url>
  <url><loc>https://site.test/p/good-two</loc><lastmod>2026-07-16</lastmod></url>
  <url><loc>https://site.test/p/not-reached</loc></url>
</urlset>""",
        )
    )
    async with httpx.AsyncClient() as client:
        result = await SitemapFetcher(HttpPolicy(client)).fetch(
            source(), source().access_methods[0], FetchState(), 1
        )

    assert [item.title for item in result.items] == ["Good Two"]
    assert len(result.warnings) == 2
    assert all("secret" not in warning for warning in result.warnings)


@pytest.mark.asyncio
@respx.mock
async def test_sitemap_304_is_no_change() -> None:
    from newsradar.ingestion.fetchers.sitemap import SitemapFetcher

    route = respx.get("https://site.test/sitemap.xml").mock(
        return_value=httpx.Response(304)
    )
    async with httpx.AsyncClient() as client:
        result = await SitemapFetcher(HttpPolicy(client)).fetch(
            source(), source().access_methods[0], FetchState(etag="old"), 5
        )

    assert result.outcome is FetchOutcome.NO_CHANGE
    assert route.calls[0].request.headers["if-none-match"] == "old"


@pytest.mark.asyncio
@respx.mock
async def test_sitemap_index_fails_closed() -> None:
    from newsradar.ingestion.fetchers.sitemap import SitemapFetcher

    respx.get("https://site.test/sitemap.xml").mock(
        return_value=httpx.Response(
            200,
            content=b"<sitemapindex><sitemap><loc>https://site.test/child.xml</loc></sitemap></sitemapindex>",
        )
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="unsupported_sitemap_index"):
            await SitemapFetcher(HttpPolicy(client)).fetch(
                source(), source().access_methods[0], FetchState(), 5
            )


@pytest.mark.asyncio
async def test_factory_selects_credential_free_sitemap_fetcher() -> None:
    from newsradar.ingestion.fetchers.sitemap import SitemapFetcher

    async with httpx.AsyncClient() as client:
        fetcher = FetcherFactory(HttpPolicy(client)).for_method(
            source().access_methods[0], credential_free_only=True
        )

    assert isinstance(fetcher, SitemapFetcher)
