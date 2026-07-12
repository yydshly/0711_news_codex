import httpx
import pytest
import respx

from newsradar.ingestion.fetchers.base import FetchState, HttpPolicy
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
async def test_youtube_reads_official_metadata_without_captions_or_key_payload() -> None:
    data = valid_source()
    data["access_methods"][0].update(
        {
            "kind": "rest_api",
            "url": "https://www.googleapis.com/youtube/v3/search",
            "params": {"channelId": "channel"},
        }
    )
    source = SourceDefinition.model_validate(data)
    respx.get("https://www.googleapis.com/youtube/v3/search").mock(
        return_value=httpx.Response(200, json={"items": [{"id": {"videoId": "abc"}}]})
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
