import gzip

import httpx
import pytest

import newsradar.research.probes.html as html_module
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
        """<link rel="canonical" href="https://news.example/a?token=leak#fragment">
        <script type="application/ld+json">{"headline":"Safe","nested":
        {"password":"leak","url":"https://api.example/item?access_token=leak#x"}}</script>
        <script type="application/json">{"authorization":"Bearer leak",
        "items":[{"secret":"leak"}]}</script>
        <meta property="og:url" content="https://og.example/post?cookie=leak#part">""",
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


@pytest.mark.asyncio
async def test_html_parse_error_keeps_response_evidence(monkeypatch) -> None:
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
    monkeypatch.setattr(
        html_module._MetadataParser,
        "feed",
        lambda self, value: (_ for _ in ()).throw(ValueError("bad html")),
    )

    async def responder(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, headers={"etag": '"html"'}, text="<html>")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(responder), trust_env=False
    ) as client:
        result = await HtmlResearchProbe(HttpPolicy(client)).probe(source, candidate)

    assert result.error_code == "ValueError"
    assert result.http_status == 200
    assert result.final_url == "https://example.test/page"
    assert result.etag == '"html"'
    assert result.latency_ms is not None


@pytest.mark.asyncio
async def test_html_robots_block_keeps_terms_review_required() -> None:
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
        return httpx.Response(403, text="denied")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(responder), trust_env=False
    ) as client:
        result = await HtmlResearchProbe(HttpPolicy(client)).probe(source, candidate)
    assert result.metadata["terms_review_required"] is True
