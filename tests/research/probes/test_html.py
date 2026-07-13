import gzip

import httpx
import pytest

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.research.probes.html import HtmlResearchProbe
from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition

from ...test_source_schema import valid_source


def test_html_probe_only_inspects_static_metadata_without_fetching() -> None:
    source = SourceDefinition.model_validate(valid_source())
    candidate = AcquisitionCandidate.model_validate(
        {
            "key": "static-html",
            "kind": "html",
            "implementation": "httpx",
            "officiality": "official",
            "authentication": "none",
            "roles": ["metadata"],
            "fields": ["title"],
            "limitations": [],
            "evidence": ["https://example.test/page"],
            "reviewed_at": "2026-07-12",
            "sample_status": "not_run",
            "decision": "manual_only",
        }
    )
    result = HtmlResearchProbe().inspect(
        source, candidate, '<meta property="og:title" content="Safe">'
    )
    assert result.outcome.value == "partial"
    assert result.metadata["static_only"] is True
    assert result.metadata["open_graph"] is True


def test_html_metadata_recursively_redacts_sensitive_nested_json_and_url_parts() -> None:
    source = SourceDefinition.model_validate(valid_source())
    candidate = AcquisitionCandidate.model_validate(
        {
            "key": "static-html",
            "kind": "html",
            "implementation": "httpx",
            "officiality": "official",
            "authentication": "none",
            "roles": ["metadata"],
            "fields": ["title"],
            "limitations": [],
            "evidence": ["https://example.test/page"],
            "reviewed_at": "2026-07-12",
            "sample_status": "not_run",
            "decision": "manual_only",
        }
    )
    result = HtmlResearchProbe().inspect(
        source,
        candidate,
        '''<link rel="canonical" href="https://news.example/a?token=leak#fragment">
        <script type="application/ld+json">{"headline":"Safe","nested":
        {"password":"leak","url":"https://api.example/item?access_token=leak#x"}}</script>
        <script type="application/json">{"authorization":"Bearer leak",
        "items":[{"secret":"leak"}]}</script>
        <meta property="og:url" content="https://og.example/post?cookie=leak#part">''',
    )

    rendered = str(result.model_dump(mode="json"))
    assert "leak" not in rendered
    assert "token" not in rendered.lower()
    assert "password" not in rendered.lower()
    assert "authorization" not in rendered.lower()
    assert "https://news.example/a" in rendered
    assert "https://api.example/item" in rendered


@pytest.mark.asyncio
async def test_html_probe_reads_a_gzip_encoded_static_page_once() -> None:
    source = SourceDefinition.model_validate(valid_source())
    candidate = AcquisitionCandidate.model_validate(
        {
            "key": "static-html",
            "kind": "html",
            "implementation": "httpx",
            "officiality": "official",
            "authentication": "none",
            "roles": ["metadata"],
            "fields": ["title"],
            "limitations": [],
            "evidence": ["https://example.test/page"],
            "reviewed_at": "2026-07-12",
            "sample_status": "not_run",
            "decision": "manual_only",
        }
    )

    async def responder(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            content=gzip.compress(b'<meta property="og:title" content="Safe">'),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(responder), trust_env=False
    ) as client:
        result = await HtmlResearchProbe(HttpPolicy(client)).probe(source, candidate)

    assert result.outcome.value == "partial"
    assert result.metadata["open_graph"] is True
