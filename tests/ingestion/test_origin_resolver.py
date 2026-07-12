from __future__ import annotations

import httpx
import pytest
import respx

from newsradar.ingestion.attribution import OriginResolutionStatus
from newsradar.ingestion.origin_resolver import OriginResolver


class ExplodingStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        raise AssertionError("article body was consumed")
        yield b""

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
@respx.mock
async def test_resolver_returns_attribution_for_direct_public_publisher_url() -> None:
    route = respx.get("https://publisher.test/story").mock(return_value=httpx.Response(200))
    async with httpx.AsyncClient() as client:
        value = await OriginResolver(client).resolve("https://publisher.test/story")

    assert value.publisher_name == "Publisher"
    assert value.publisher_url == "https://publisher.test/story"
    assert value.discovery_url == "https://publisher.test/story"
    assert value.resolution_status is OriginResolutionStatus.RESOLVED
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_resolver_follows_relative_redirects_without_reading_article_body() -> None:
    respx.get("https://news.google.test/read").mock(
        return_value=httpx.Response(302, headers={"location": "/out/story"})
    )
    route = respx.get("https://news.google.test/out/story").mock(
        return_value=httpx.Response(200, content=b"article body must not be consumed")
    )
    async with httpx.AsyncClient() as client:
        value = await OriginResolver(client).resolve("https://news.google.test/read")

    assert value.publisher_url == "https://news.google.test/out/story"
    assert route.calls[0].request.method == "GET"


@pytest.mark.asyncio
@respx.mock
async def test_resolver_does_not_consume_final_article_response_body() -> None:
    respx.get("https://publisher.test/no-read").mock(
        return_value=httpx.Response(200, stream=ExplodingStream())
    )
    async with httpx.AsyncClient() as client:
        value = await OriginResolver(client).resolve("https://publisher.test/no-read")

    assert value.resolution_status is OriginResolutionStatus.RESOLVED


@pytest.mark.asyncio
@respx.mock
async def test_resolver_rejects_redirect_loops_private_and_cross_scheme_destinations() -> None:
    respx.get("https://discovery.test/loop").mock(
        return_value=httpx.Response(302, headers={"location": "/loop"})
    )
    respx.get("https://discovery.test/http").mock(
        return_value=httpx.Response(302, headers={"location": "http://publisher.test/story"})
    )
    async with httpx.AsyncClient() as client:
        resolver = OriginResolver(client)
        loop = await resolver.resolve("https://discovery.test/loop")
        cross_scheme = await resolver.resolve("https://discovery.test/http")
        private = await resolver.resolve("https://127.0.0.1/story")

    assert loop.resolution_status is OriginResolutionStatus.TOO_MANY_REDIRECTS
    assert cross_scheme.resolution_status is OriginResolutionStatus.UNRESOLVED
    assert private.resolution_status is OriginResolutionStatus.UNRESOLVED


@pytest.mark.asyncio
@respx.mock
async def test_resolver_caps_redirect_chain_at_five_and_rejects_missing_publisher() -> None:
    for number in range(5):
        respx.get(f"https://discovery.test/{number}").mock(
            return_value=httpx.Response(302, headers={"location": f"/{number + 1}"})
        )
    respx.get("https://news.google.com/rss").mock(return_value=httpx.Response(200))
    async with httpx.AsyncClient() as client:
        resolver = OriginResolver(client)
        capped = await resolver.resolve("https://discovery.test/0")
        missing = await resolver.resolve("https://news.google.com/rss")

    assert capped.resolution_status is OriginResolutionStatus.TOO_MANY_REDIRECTS
    assert missing.resolution_status is OriginResolutionStatus.UNRESOLVED
