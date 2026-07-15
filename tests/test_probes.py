from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from newsradar.sources.probes.base import ProbeOutcome
from newsradar.sources.probes.factory import ProbeFactory
from newsradar.sources.probes.runner import ProbeRunner
from newsradar.sources.schema import AccessMethod, SourceDefinition
from newsradar.sources.yaml_loader import load_source_tree

from .test_source_schema import valid_source


class Credentials:
    def __init__(self, values: dict[str, str]):
        self.values = values

    def require(self, name: str) -> str:
        return self.values[name]


def source_with(method: dict, expected_fields: list[str] | None = None) -> SourceDefinition:
    data = valid_source()
    data["access_methods"] = [method]
    if expected_fields is not None:
        data["expected_fields"] = expected_fields
    return SourceDefinition.model_validate(data)


@pytest.mark.asyncio
async def test_openai_youtube_atom_is_successful_without_engagement_requirement() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}
    source = sources["openai-youtube"]
    method = next(method for method in source.access_methods if method.kind.value == "atom")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                "<feed xmlns='http://www.w3.org/2005/Atom'>"
                "<entry><id>video-1</id><title>OpenAI update</title>"
                "<link href='https://www.youtube.com/watch?v=video-1'/>"
                "<published>2026-07-14T00:00:00Z</published>"
                "<summary>Official video</summary></entry></feed>"
            ),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ProbeFactory(client).create(method).probe(source, method)

    assert result.outcome is ProbeOutcome.SUCCESS
    assert result.field_completeness == 1.0


@pytest.mark.asyncio
async def test_rss_probe_reports_freshness_completeness_and_cache_headers() -> None:
    feed = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>AI News</title>
      <item><guid>1</guid><title>Model released</title>
        <link>https://vendor.example/news/model</link>
        <pubDate>Fri, 10 Jul 2026 12:00:00 GMT</pubDate>
        <description>Details</description></item>
    </channel></rss>"""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=feed,
            headers={"content-type": "application/rss+xml", "etag": '"v1"'},
            request=request,
        )

    source = source_with({"kind": "rss", "url": "https://vendor.example/feed.xml", "priority": 1})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = (
            await ProbeFactory(client)
            .create(source.access_methods[0])
            .probe(source, source.access_methods[0])
        )

    assert result.outcome == ProbeOutcome.SUCCESS
    assert result.sample_count == 1
    assert result.field_completeness == 1.0
    assert result.etag == '"v1"'
    assert result.latest_published_at == datetime(2026, 7, 10, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_probe_returns_blocked_when_required_credential_is_missing() -> None:
    source = source_with(
        {
            "kind": "rest_api",
            "url": "https://api.github.com/repos/example/project/releases",
            "priority": 1,
            "auth_env": "GITHUB_TOKEN",
        }
    )
    async with httpx.AsyncClient() as client:
        result = (
            await ProbeFactory(client, credentials=Credentials({}))
            .create(source.access_methods[0])
            .probe(source, source.access_methods[0])
        )

    assert result.outcome == ProbeOutcome.BLOCKED
    assert result.error_code == "missing_credential"
    assert "GITHUB_TOKEN" in result.reason


@pytest.mark.asyncio
async def test_json_probe_fingerprints_schema_and_rate_limit_headers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "id": 42,
                    "title": "Release",
                    "url": "https://news.example/42",
                    "time": 1783684800,
                    "score": 100,
                    "by": "author",
                }
            ],
            headers={"x-ratelimit-remaining": "99", "content-type": "application/json"},
            request=request,
        )

    source = source_with(
        {"kind": "public_api", "url": "https://api.example/items", "priority": 1},
        ["title", "canonical_url", "published_at", "author", "engagement"],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = (
            await ProbeFactory(client)
            .create(source.access_methods[0])
            .probe(source, source.access_methods[0])
        )

    assert result.outcome == ProbeOutcome.SUCCESS
    assert result.schema_fingerprint
    assert result.rate_limit_remaining == 99
    assert result.field_completeness == 1.0


@pytest.mark.asyncio
async def test_runner_isolates_source_failures() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "broken.example":
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(
            200, json=[{"title": "ok", "url": "https://ok.example/1"}], request=request
        )

    good = source_with(
        {"kind": "public_api", "url": "https://good.example/items", "priority": 1},
        ["title", "canonical_url"],
    )
    good.id = "good-source"
    bad = source_with({"kind": "public_api", "url": "https://broken.example/items", "priority": 1})
    bad.id = "bad-source"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await ProbeRunner(ProbeFactory(client)).probe_all([good, bad])

    assert results["good-source"].outcome == ProbeOutcome.SUCCESS
    assert results["bad-source"].outcome == ProbeOutcome.FAILED
    assert results["bad-source"].error_code == "connection_error"


def test_html_requires_manual_approval() -> None:
    with pytest.raises(ValueError, match="manual approval"):
        AccessMethod.model_validate(
            {"kind": "html", "url": "https://vendor.example/news", "priority": 1}
        )


@pytest.mark.asyncio
async def test_probe_preserves_query_parameters_embedded_in_url() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["search_query"] == "cat:cs.AI"
        return httpx.Response(
            200,
            text=(
                "<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'>"
                "<entry><id>https://arxiv.org/abs/1</id><title>Paper</title>"
                "<link href='https://arxiv.org/abs/1'/><published>2026-07-10T12:00:00Z</published>"
                "<author><name>Alice</name></author><summary>Abstract</summary></entry></feed>"
            ),
            request=request,
        )

    source = source_with(
        {
            "kind": "atom",
            "url": "https://export.arxiv.org/api/query?search_query=cat:cs.AI",
            "priority": 1,
        },
        ["title", "canonical_url", "published_at", "author", "summary"],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = (
            await ProbeFactory(client)
            .create(source.access_methods[0])
            .probe(source, source.access_methods[0])
        )
    assert result.outcome == ProbeOutcome.SUCCESS


@pytest.mark.asyncio
async def test_runner_uses_reviewed_fallback_after_primary_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "primary.example":
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            json=[{"title": "ok", "url": "https://fallback.example/item"}],
            request=request,
        )

    data = valid_source()
    data["expected_fields"] = ["title", "canonical_url"]
    data["access_methods"] = [
        {"kind": "public_api", "url": "https://primary.example/items", "priority": 1},
        {"kind": "public_api", "url": "https://fallback.example/items", "priority": 2},
    ]
    source = SourceDefinition.model_validate(data)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ProbeRunner(ProbeFactory(client)).probe_one(source)
    assert result.outcome == ProbeOutcome.SUCCESS
    assert result.access_url == "https://fallback.example/items"


@pytest.mark.asyncio
async def test_unimplemented_reviewed_html_is_safely_blocked() -> None:
    data = valid_source()
    data["access_methods"] = [
        {
            "kind": "html",
            "url": "https://vendor.example/news",
            "priority": 1,
            "requires_manual_approval": True,
        }
    ]
    source = SourceDefinition.model_validate(data)
    async with httpx.AsyncClient() as client:
        result = await ProbeRunner(ProbeFactory(client)).probe_one(source)
    assert result.outcome == ProbeOutcome.BLOCKED
    assert result.error_code == "unsupported_access_kind"


@pytest.mark.asyncio
async def test_empty_json_response_is_reported_as_no_content() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[], request=request)

    source = source_with(
        {"kind": "public_api", "url": "https://api.example/items", "priority": 1},
        ["title", "canonical_url"],
    )
    method = source.access_methods[0]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ProbeFactory(client).create(method).probe(source, method)

    assert result.outcome is ProbeOutcome.DEGRADED
    assert result.sample_count == 0
    assert result.error_code == "no_content"
    assert result.suggested_status.value == "degraded"


@pytest.mark.asyncio
async def test_empty_rss_feed_is_reported_as_no_content() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<?xml version='1.0'?><rss version='2.0'><channel /></rss>",
            request=request,
        )

    source = source_with(
        {"kind": "rss", "url": "https://feeds.example/empty.xml", "priority": 1},
        ["title", "canonical_url"],
    )
    method = source.access_methods[0]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ProbeFactory(client).create(method).probe(source, method)

    assert result.outcome is ProbeOutcome.DEGRADED
    assert result.sample_count == 0
    assert result.error_code == "no_content"
    assert result.suggested_status.value == "degraded"


@pytest.mark.asyncio
async def test_json_sample_with_missing_expected_field_is_incomplete_fields() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"title": "Only a title"}], request=request)

    source = source_with(
        {"kind": "public_api", "url": "https://api.example/items", "priority": 1},
        ["title", "canonical_url"],
    )
    method = source.access_methods[0]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ProbeFactory(client).create(method).probe(source, method)

    assert result.outcome is ProbeOutcome.DEGRADED
    assert result.sample_count == 1
    assert result.error_code == "incomplete_fields"
