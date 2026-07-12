import httpx
import pytest
import respx

from newsradar.ingestion.fetchers.base import FetchState, HttpPolicy
from newsradar.ingestion.fetchers.bluesky import BlueskyFetcher
from newsradar.ingestion.schema import FetchOutcome
from newsradar.sources.schema import SourceDefinition

from ...test_source_schema import valid_source


def bluesky_source(
    endpoint: str = "app.bsky.feed.getAuthorFeed", **params: str
) -> SourceDefinition:
    data = valid_source()
    data["access_methods"][0].update(
        {
            "kind": "public_api",
            "url": f"https://public.api.bsky.app/xrpc/{endpoint}",
            "params": params or {"actor": "researcher.example"},
        }
    )
    return SourceDefinition.model_validate(data)


@pytest.mark.asyncio
@respx.mock
async def test_bluesky_author_feed_preserves_identity_metrics_and_thread_root() -> None:
    source = bluesky_source()
    respx.get(str(source.access_methods[0].url)).mock(
        return_value=httpx.Response(
            200,
            json={
                "cursor": "next-page",
                "feed": [
                    {
                        "post": {
                            "uri": "at://did:plc:alice/app.bsky.feed.post/abc",
                            "cid": "bafy-cid",
                            "author": {"did": "did:plc:alice", "handle": "alice.example"},
                            "record": {
                                "text": "Model release",
                                "createdAt": "2026-07-10T12:00:00Z",
                                "reply": {
                                    "root": {"uri": "at://did:plc:root/app.bsky.feed.post/root"}
                                },
                            },
                            "likeCount": 5,
                            "repostCount": 2,
                            "replyCount": 1,
                        }
                    }
                ],
            },
        )
    )
    async with httpx.AsyncClient() as client:
        result = await BlueskyFetcher(HttpPolicy(client)).fetch(
            source, source.access_methods[0], FetchState(), 5
        )
    item = result.items[0]
    assert item.external_id == "at://did:plc:alice/app.bsky.feed.post/abc#bafy-cid"
    assert item.author_account_id == "did:plc:alice"
    assert item.author_handle == "alice.example"
    assert item.thread_root_id == "at://did:plc:root/app.bsky.feed.post/root"
    assert item.engagement == {"likes": 5, "reposts": 2, "replies": 1}
    assert str(item.canonical_url) == "https://bsky.app/profile/alice.example/post/abc"
    assert result.next_cursor == "next-page"


@pytest.mark.asyncio
@respx.mock
async def test_bluesky_uses_registered_query_and_same_endpoint_cursor() -> None:
    source = bluesky_source("app.bsky.feed.searchPosts", q="from:alice AI")
    cursor = f"{source.access_methods[0].url}?cursor=opaque"
    route = respx.get(cursor).mock(return_value=httpx.Response(200, json={"posts": []}))
    async with httpx.AsyncClient() as client:
        result = await BlueskyFetcher(HttpPolicy(client)).fetch(
            source, source.access_methods[0], FetchState(cursor=cursor), 5
        )
    assert route.called
    assert result.outcome is FetchOutcome.SUCCEEDED


@pytest.mark.asyncio
@respx.mock
async def test_bluesky_skips_unavailable_posts_and_degrades_search_errors() -> None:
    source = bluesky_source("app.bsky.feed.searchPosts", q="AI")
    respx.get(str(source.access_methods[0].url)).mock(return_value=httpx.Response(503, json={}))
    async with httpx.AsyncClient() as client:
        result = await BlueskyFetcher(HttpPolicy(client, retries=0)).fetch(
            source, source.access_methods[0], FetchState(), 5
        )
    assert result.outcome is FetchOutcome.PARTIAL
    assert result.error_code == "search_degraded"


@pytest.mark.asyncio
async def test_bluesky_rejects_unregistered_target_or_cursor() -> None:
    source = bluesky_source("app.bsky.feed.getAuthorFeed")
    async with httpx.AsyncClient() as client:
        fetcher = BlueskyFetcher(HttpPolicy(client))
        with pytest.raises(ValueError, match="unregistered_bluesky_cursor"):
            await fetcher.fetch(
                source,
                source.access_methods[0],
                FetchState(cursor="https://public.api.bsky.app/xrpc/other"),
                5,
            )
    data = valid_source()
    data["access_methods"][0].update(
        {
            "kind": "public_api",
            "url": "https://api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
            "params": {"actor": "a"},
        }
    )
    bad = SourceDefinition.model_validate(data)
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="unregistered_bluesky_target"):
            await BlueskyFetcher(HttpPolicy(client)).fetch(
                bad, bad.access_methods[0], FetchState(), 5
            )
