import httpx
import pytest
import respx

from newsradar.ingestion.fetchers.base import FetchState, HttpPolicy
from newsradar.ingestion.fetchers.hackernews import HackerNewsFetcher
from newsradar.sources.schema import SourceDefinition

from ...test_source_schema import valid_source


@pytest.mark.asyncio
@respx.mock
async def test_hackernews_skips_dead_items_without_opening_story_url() -> None:
    data = valid_source()
    data["access_methods"][0].update(
        {"kind": "public_api", "url": "https://hacker-news.firebaseio.com/v0/topstories.json"}
    )
    source = SourceDefinition.model_validate(data)
    respx.get("https://hacker-news.firebaseio.com/v0/topstories.json").mock(
        return_value=httpx.Response(200, json=[1, 2])
    )
    respx.get("https://hacker-news.firebaseio.com/v0/item/1.json").mock(
        return_value=httpx.Response(200, json={"id": 1, "dead": True})
    )
    respx.get("https://hacker-news.firebaseio.com/v0/item/2.json").mock(
        return_value=httpx.Response(
            200, json={"id": 2, "type": "story", "title": "Story", "url": "https://article.test/a"}
        )
    )
    async with httpx.AsyncClient() as client:
        result = await HackerNewsFetcher(HttpPolicy(client)).fetch(
            source, source.access_methods[0], FetchState(), 5
        )
    assert [item.external_id for item in result.items] == ["2"]
