import httpx
import pytest
import respx

from newsradar.ingestion.fetchers.arxiv import ArxivFetcher
from newsradar.ingestion.fetchers.base import FetchState, HttpPolicy
from newsradar.sources.schema import SourceDefinition

from ...test_source_schema import valid_source


@pytest.mark.asyncio
@respx.mock
async def test_arxiv_retains_authors_and_version_without_pdf_request() -> None:
    data = valid_source()
    data["access_methods"][0].update({"kind": "atom", "url": "https://export.arxiv.org/api/query"})
    source = SourceDefinition.model_validate(data)
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(
            200,
            content=(
                b"<feed xmlns='http://www.w3.org/2005/Atom'><entry>"
                b"<id>http://arxiv.org/abs/1234.5678v2</id><title> Paper </title>"
                b"<summary>S</summary><author><name>Ada</name></author>"
                b"<link rel='alternate' href='https://arxiv.org/abs/1234.5678v2'/>"
                b"</entry></feed>"
            ),
        )
    )
    async with httpx.AsyncClient() as client:
        result = await ArxivFetcher(HttpPolicy(client), delay_seconds=0).fetch(
            source, source.access_methods[0], FetchState(), 5
        )
    assert result.items[0].authors == ("Ada",)
    assert result.items[0].raw_payload["version"] == "2"
