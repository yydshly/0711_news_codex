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
    assert result.http_status == 503
    assert result.final_url == "https://example.test/robots.txt"
    assert result.blocked_condition == "robots"
    assert result.latency_ms is not None


@pytest.mark.asyncio
async def test_sitemap_xml_error_keeps_response_evidence() -> None:
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
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, headers={"etag": '"xml"'}, content=b"<urlset>")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(responder), trust_env=False
    ) as client:
        result = await SitemapResearchProbe(HttpPolicy(client)).probe(source, candidate)

    assert result.error_code == "ParseError"
    assert result.http_status == 200
    assert result.final_url == "https://example.test/sitemap.xml"
    assert result.etag == '"xml"'
    assert result.latency_ms is not None


@pytest.mark.asyncio
async def test_sitemap_sample_canonical_url_removes_sensitive_parts() -> None:
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
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(
            200,
            text="<urlset><url><loc>https://example.test/a?cookie=secret#part</loc></url></urlset>",
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(responder), trust_env=False
    ) as client:
        result = await SitemapResearchProbe(HttpPolicy(client)).probe(source, candidate)
    assert result.samples[0].canonical_url == "https://example.test/a"
