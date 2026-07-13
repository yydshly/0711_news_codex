import httpx
import pytest

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.research.probes.sitemap import SitemapResearchProbe
from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition

from ...test_source_schema import valid_source


@pytest.mark.asyncio
async def test_robots_server_error_blocks_sitemap_content_probe() -> None:
    source = SourceDefinition.model_validate(valid_source())
    candidate = AcquisitionCandidate.model_validate(
        {
            "key": "site-map",
            "kind": "sitemap",
            "implementation": "httpx",
            "officiality": "official",
            "authentication": "none",
            "roles": ["discovery"],
            "fields": ["url"],
            "limitations": [],
            "evidence": ["https://example.test/sitemap.xml"],
            "reviewed_at": "2026-07-12",
            "sample_status": "not_run",
            "decision": "supplement",
        }
    )

    async def responder(request):
        return httpx.Response(503 if request.url.path == "/robots.txt" else 200, text="<urlset/>")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(responder), trust_env=False
    ) as client:
        result = await SitemapResearchProbe(HttpPolicy(client)).probe(source, candidate)
    assert result.outcome.value == "blocked"
    assert result.error_code == "robots_unavailable"
