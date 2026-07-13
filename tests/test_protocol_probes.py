from __future__ import annotations

import httpx
import pytest

from newsradar.sources.probes.base import ProbeOutcome
from newsradar.sources.probes.factory import ProbeFactory
from newsradar.sources.probes.protocols import synthetic_response

from .test_probes import source_with


class Credentials:
    def __init__(self, values: dict[str, str]):
        self.values = values

    def require(self, name: str) -> str:
        return self.values[name]


def test_synthetic_response_drops_wire_encoding_headers() -> None:
    request = httpx.Request("GET", "https://public.api.bsky.app/feed")
    original = httpx.Response(
        200,
        headers={"content-encoding": "gzip", "content-length": "999"},
        request=request,
    )

    response = synthetic_response(original, {"items": []})

    assert "content-encoding" not in response.headers
    assert response.headers["content-length"] != "999"
    assert response.json() == {"items": []}


@pytest.mark.asyncio
async def test_hackernews_probe_fetches_story_details() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("topstories.json"):
            return httpx.Response(200, json=[42], request=request)
        return httpx.Response(
            200,
            json={
                "id": 42,
                "title": "A release",
                "url": "https://vendor.example/release",
                "time": 1783684800,
                "score": 120,
                "by": "alice",
            },
            request=request,
        )

    source = source_with(
        {
            "kind": "public_api",
            "url": "https://hacker-news.firebaseio.com/v0/topstories.json",
            "priority": 1,
        },
        ["title", "canonical_url", "published_at", "author", "engagement"],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = (
            await ProbeFactory(client)
            .create(source.access_methods[0])
            .probe(source, source.access_methods[0])
        )
    assert result.outcome == ProbeOutcome.SUCCESS
    assert result.samples[0].external_id == "42"


@pytest.mark.asyncio
async def test_youtube_probe_normalizes_playlist_items() -> None:

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["key"] == "test-key"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "playlist-item",
                        "snippet": {
                            "title": "Model demo",
                            "description": "Demo description",
                            "publishedAt": "2026-07-10T12:00:00Z",
                            "channelTitle": "Vendor",
                            "resourceId": {"videoId": "video-1"},
                        },
                    }
                ]
            },
            request=request,
        )

    source = source_with(
        {
            "kind": "rest_api",
            "url": "https://www.googleapis.com/youtube/v3/playlistItems",
            "priority": 1,
            "auth_env": "YOUTUBE_API_KEY",
            "params": {"part": "snippet", "playlistId": "uploads"},
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = (
            await ProbeFactory(client, credentials=Credentials({"YOUTUBE_API_KEY": "test-key"}))
            .create(source.access_methods[0])
            .probe(source, source.access_methods[0])
        )
    assert result.samples[0].canonical_url == "https://www.youtube.com/watch?v=video-1"
    assert result.samples[0].author == "Vendor"


@pytest.mark.asyncio
async def test_bluesky_probe_normalizes_author_feed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "feed": [
                    {
                        "post": {
                            "uri": "at://did/app.bsky.feed.post/1",
                            "author": {"displayName": "Researcher", "handle": "r.example"},
                            "record": {"text": "New model", "createdAt": "2026-07-10T12:00:00Z"},
                            "likeCount": 9,
                        }
                    }
                ]
            },
            request=request,
        )

    source = source_with(
        {
            "kind": "public_api",
            "url": "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
            "priority": 1,
            "params": {"actor": "r.example"},
        },
        ["title", "canonical_url", "published_at", "author", "engagement"],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = (
            await ProbeFactory(client)
            .create(source.access_methods[0])
            .probe(source, source.access_methods[0])
        )
    assert result.outcome == ProbeOutcome.SUCCESS
    assert result.samples[0].engagement == 9
    assert result.samples[0].canonical_url == "https://bsky.app/profile/r.example/post/1"


@pytest.mark.asyncio
async def test_reddit_probe_blocks_without_oauth_credentials() -> None:
    class MissingCredentials:
        def require(self, name: str) -> str:
            raise KeyError(name)

    def reject_network(_: httpx.Request) -> httpx.Response:
        pytest.fail("missing OAuth credentials must block before any network request")

    source = source_with(
        {
            "kind": "rest_api",
            "url": "https://oauth.reddit.com/r/LocalLLaMA/new",
            "priority": 1,
            "params": {"limit": "5"},
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(reject_network)) as client:
        result = (
            await ProbeFactory(client, credentials=MissingCredentials())
            .create(source.access_methods[0])
            .probe(source, source.access_methods[0])
        )
    assert result.outcome == ProbeOutcome.BLOCKED
    assert result.error_code == "missing_oauth_credentials"


@pytest.mark.asyncio
async def test_github_release_body_counts_as_summary() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "name": "v1.0",
                    "html_url": "https://github.com/example/project/releases/tag/v1.0",
                    "published_at": "2026-07-10T12:00:00Z",
                    "author": {"login": "maintainer"},
                    "body": "Release notes",
                }
            ],
            request=request,
        )

    source = source_with(
        {
            "kind": "rest_api",
            "url": "https://api.github.com/repos/example/project/releases",
            "priority": 1,
        },
        ["title", "canonical_url", "published_at", "author", "summary"],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = (
            await ProbeFactory(client)
            .create(source.access_methods[0])
            .probe(source, source.access_methods[0])
        )
    assert result.outcome == ProbeOutcome.SUCCESS
    assert result.samples[0].summary == "Release notes"


@pytest.mark.asyncio
async def test_gdelt_compact_seen_date_is_parsed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "title": "AI announcement",
                        "url": "https://publisher.example/story",
                        "seendate": "20260710T120000Z",
                        "domain": "publisher.example",
                    }
                ]
            },
            request=request,
        )

    source = source_with(
        {"kind": "public_api", "url": "https://api.gdeltproject.org/api/v2/doc/doc", "priority": 1},
        ["title", "canonical_url", "published_at"],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = (
            await ProbeFactory(client)
            .create(source.access_methods[0])
            .probe(source, source.access_methods[0])
        )
    assert result.outcome == ProbeOutcome.SUCCESS
    assert result.samples[0].published_at is not None
