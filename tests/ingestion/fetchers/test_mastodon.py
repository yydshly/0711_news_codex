import asyncio

import httpx
import pytest
import respx

from newsradar.ingestion.fetchers.base import FetchState, HttpPolicy
from newsradar.ingestion.fetchers.mastodon import MastodonFetcher
from newsradar.ingestion.schema import FetchOutcome
from newsradar.sources.schema import SourceDefinition

from ...test_source_schema import valid_source


def mastodon_source(path: str = "/api/v1/accounts/42/statuses", **params: str) -> SourceDefinition:
    data = valid_source()
    data["access_methods"][0].update(
        {
            "kind": "public_api",
            "url": f"https://social.example{path}",
            "params": params or {"limit": "20"},
        }
    )
    return SourceDefinition.model_validate(data)


@pytest.mark.asyncio
@respx.mock
async def test_mastodon_account_statuses_preserve_instance_identity_and_warning() -> None:
    source = mastodon_source()
    respx.get(str(source.access_methods[0].url)).mock(
        return_value=httpx.Response(
            200,
            headers={
                "Link": '<https://social.example/api/v1/accounts/42/statuses?max_id=8>; rel="next"'
            },
            json=[
                {
                    "id": "9",
                    "url": "https://social.example/@alice/9",
                    "content": "<p>Release</p>",
                    "created_at": "2026-07-10T12:00:00Z",
                    "account": {"id": "42", "acct": "alice", "display_name": "Alice"},
                    "favourites_count": 3,
                    "reblogs_count": 2,
                    "replies_count": 1,
                    "spoiler_text": "content warning",
                },
                {"id": "8", "deleted": True},
            ],
        )
    )
    async with httpx.AsyncClient() as client:
        result = await MastodonFetcher(HttpPolicy(client)).fetch(
            source, source.access_methods[0], FetchState(), 5
        )
    item = result.items[0]
    assert item.external_id == "social.example:9"
    assert item.author_account_id == "social.example:42"
    assert item.author_handle == "alice@social.example"
    assert item.title == "content warning"
    assert item.engagement == {"favourites": 3, "reblogs": 2, "replies": 1}
    assert result.next_cursor == "https://social.example/api/v1/accounts/42/statuses?max_id=8"


@pytest.mark.asyncio
@respx.mock
async def test_mastodon_429_is_a_per_instance_rate_limit() -> None:
    source = mastodon_source()
    respx.get(str(source.access_methods[0].url)).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "12"})
    )
    async with httpx.AsyncClient() as client:
        result = await MastodonFetcher(HttpPolicy(client, retries=0)).fetch(
            source, source.access_methods[0], FetchState(), 5
        )
    assert result.outcome is FetchOutcome.FAILED
    assert result.error_code == "rate_limited"
    assert result.retry_after_seconds == 12


@pytest.mark.asyncio
async def test_mastodon_rejects_discovery_and_other_instance_cursors() -> None:
    source = mastodon_source("/api/v1/timelines/public")
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="unbounded_mastodon_discovery"):
            await MastodonFetcher(HttpPolicy(client)).fetch(
                source, source.access_methods[0], FetchState(), 5
            )


@pytest.mark.asyncio
@respx.mock
async def test_mastodon_allows_only_local_configured_public_timeline() -> None:
    source = mastodon_source("/api/v1/timelines/public", local="true")
    respx.get(str(source.access_methods[0].url)).mock(return_value=httpx.Response(200, json=[]))
    async with httpx.AsyncClient() as client:
        result = await MastodonFetcher(HttpPolicy(client)).fetch(
            source, source.access_methods[0], FetchState(), 5
        )
    assert result.outcome is FetchOutcome.SUCCEEDED
    source = mastodon_source()
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="unregistered_mastodon_instance"):
            await MastodonFetcher(HttpPolicy(client)).fetch(
                source,
                source.access_methods[0],
                FetchState(cursor="https://other.example/api/v1/accounts/42/statuses"),
                5,
            )


@pytest.mark.asyncio
async def test_mastodon_requests_share_the_http_policy_host_limit() -> None:
    source = mastodon_source()
    in_flight = 0
    maximum = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, maximum
        in_flight += 1
        maximum = max(maximum, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return httpx.Response(200, json=[], request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = MastodonFetcher(HttpPolicy(client, per_host=1))
        await asyncio.gather(
            *(fetcher.fetch(source, source.access_methods[0], FetchState(), 5) for _ in range(3))
        )
    assert maximum == 1
