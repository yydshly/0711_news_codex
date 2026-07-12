import httpx
import pytest
import respx

from newsradar.ingestion.fetchers.base import FetchState, HttpPolicy
from newsradar.ingestion.fetchers.rss import RssFetcher
from newsradar.ingestion.schema import FetchOutcome
from newsradar.sources.schema import SourceDefinition

from ...test_source_schema import valid_source


def source() -> SourceDefinition:
    data = valid_source()
    data["access_methods"][0].update({"kind": "rss", "url": "https://feed.test/rss"})
    return SourceDefinition.model_validate(data)


@pytest.mark.asyncio
@respx.mock
async def test_rss_uses_conditional_request_and_isolates_bad_entry() -> None:
    route = respx.get("https://feed.test/rss").mock(
        return_value=httpx.Response(
            200,
            headers={"etag": "v1"},
            content=b"""<rss><channel><item><guid>1</guid><title>Good</title><link>https://x.test/1</link></item><item><title>Bad</title></item></channel></rss>""",
        )
    )
    async with httpx.AsyncClient() as client:
        result = await RssFetcher(HttpPolicy(client)).fetch(
            source(), source().access_methods[0], FetchState(etag="old"), 5
        )
    assert result.outcome is FetchOutcome.SUCCEEDED
    assert [item.external_id for item in result.items] == ["1"]
    assert result.warnings
    assert route.calls[0].request.headers["if-none-match"] == "old"


@pytest.mark.asyncio
@respx.mock
async def test_rss_304_is_no_change() -> None:
    respx.get("https://feed.test/rss").mock(return_value=httpx.Response(304))
    async with httpx.AsyncClient() as client:
        result = await RssFetcher(HttpPolicy(client)).fetch(
            source(), source().access_methods[0], FetchState(), 5
        )
    assert result.outcome is FetchOutcome.NO_CHANGE
