import httpx
import pytest
import respx

from newsradar.ingestion.fetchers.base import FetcherFactory, FetchState, HttpPolicy
from newsradar.ingestion.fetchers.youtube import YouTubeFetcher
from newsradar.ingestion.schema import FetchOutcome
from newsradar.sources.schema import SourceDefinition

from ...test_source_schema import valid_source


class Credentials:
    def __init__(self, values: dict[str, str]):
        self.values = values

    def require(self, name: str) -> str:
        return self.values[name]


@pytest.mark.asyncio
@respx.mock
async def test_youtube_reads_upload_playlist_without_search_or_key_payload() -> None:
    data = valid_source()
    data["access_methods"][0].update(
        {
            "kind": "rest_api",
            "url": "https://www.googleapis.com/youtube/v3/channels",
            "params": {"id": "channel"},
        }
    )
    source = SourceDefinition.model_validate(data)
    channel = respx.get("https://www.googleapis.com/youtube/v3/channels").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {"contentDetails": {"relatedPlaylists": {"uploads": "uploads"}}}
                ]
            },
        )
    )
    playlist = respx.get("https://www.googleapis.com/youtube/v3/playlistItems").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"contentDetails": {"videoId": "abc"}}]},
        )
    )
    respx.get("https://www.googleapis.com/youtube/v3/videos").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "abc",
                        "snippet": {
                            "title": "Demo",
                            "description": "desc",
                            "channelTitle": "Official",
                            "publishedAt": "2026-07-11T00:00:00Z",
                        },
                        "statistics": {"viewCount": "7", "likeCount": "2", "commentCount": "1"},
                    }
                ]
            },
        )
    )
    async with httpx.AsyncClient() as client:
        result = await YouTubeFetcher(
            HttpPolicy(client), Credentials({"YOUTUBE_API_KEY": "private"})
        ).fetch(source, source.access_methods[0], FetchState(), 5)
    assert result.outcome is FetchOutcome.SUCCEEDED and result.items[0].external_id == "abc"
    assert "private" not in str(result.items[0].raw_payload)
    assert "private" not in result.model_dump_json()
    assert channel.calls[0].request.url.params["id"] == "channel"
    assert playlist.calls[0].request.url.params["playlistId"] == "uploads"
    assert all(call.request.url.path != "/youtube/v3/search" for call in respx.calls)


def test_factory_selects_youtube_fetcher_for_channels_endpoint() -> None:
    data = valid_source()
    data["access_methods"][0].update(
        {
            "kind": "rest_api",
            "url": "https://www.googleapis.com/youtube/v3/channels",
            "params": {"id": "channel"},
        }
    )
    source = SourceDefinition.model_validate(data)
    client = httpx.AsyncClient()
    try:
        fetcher = FetcherFactory(HttpPolicy(client), Credentials({})).for_method(
            source.access_methods[0]
        )
        assert isinstance(fetcher, YouTubeFetcher)
    finally:
        import asyncio

        asyncio.run(client.aclose())


@pytest.mark.asyncio
@respx.mock
async def test_youtube_empty_channel_is_a_successful_zero_item_result() -> None:
    data = valid_source()
    data["access_methods"][0].update(
        {
            "kind": "rest_api",
            "url": "https://www.googleapis.com/youtube/v3/channels",
            "params": {"id": "missing"},
        }
    )
    source = SourceDefinition.model_validate(data)
    respx.get("https://www.googleapis.com/youtube/v3/channels").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    async with httpx.AsyncClient() as client:
        result = await YouTubeFetcher(
            HttpPolicy(client), Credentials({"YOUTUBE_API_KEY": "private"})
        ).fetch(source, source.access_methods[0], FetchState(), 5)

    assert result.outcome is FetchOutcome.SUCCEEDED
    assert result.items == ()
    assert result.items_received == 0
