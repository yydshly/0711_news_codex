import httpx
import pytest
import respx

from newsradar.ingestion.fetchers.base import FetchState, HttpPolicy
from newsradar.ingestion.fetchers.github import GitHubFetcher
from newsradar.ingestion.schema import FetchOutcome
from newsradar.sources.schema import SourceDefinition

from ...test_source_schema import valid_source


@pytest.mark.asyncio
@respx.mock
async def test_github_filters_drafts_and_prereleases() -> None:
    data = valid_source()
    data["access_methods"][0].update(
        {"kind": "rest_api", "url": "https://api.github.com/repos/org/repo/releases"}
    )
    source = SourceDefinition.model_validate(data)
    respx.get("https://api.github.com/repos/org/repo/releases").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "draft": True, "html_url": "https://github.com/org/repo/releases/1"},
                {"id": 2, "prerelease": True, "html_url": "https://github.com/org/repo/releases/2"},
                {"id": 3, "tag_name": "v1", "html_url": "https://github.com/org/repo/releases/3"},
            ],
        )
    )
    async with httpx.AsyncClient() as client:
        result = await GitHubFetcher(HttpPolicy(client)).fetch(
            source, source.access_methods[0], FetchState(), 5
        )
    assert [item.external_id for item in result.items] == ["3"]


@pytest.mark.asyncio
@respx.mock
async def test_github_304_is_no_change() -> None:
    data = valid_source()
    data["access_methods"][0].update(
        {"kind": "rest_api", "url": "https://api.github.com/repos/org/repo/releases"}
    )
    source = SourceDefinition.model_validate(data)
    respx.get("https://api.github.com/repos/org/repo/releases").mock(
        return_value=httpx.Response(304)
    )
    async with httpx.AsyncClient() as client:
        result = await GitHubFetcher(HttpPolicy(client)).fetch(
            source, source.access_methods[0], FetchState(), 5
        )
    assert result.outcome is FetchOutcome.NO_CHANGE
