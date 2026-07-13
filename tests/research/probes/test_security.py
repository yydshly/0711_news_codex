import httpx
import pytest

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.research.probes.feed import FeedResearchProbe
from newsradar.research.probes.safe_http import new_safe_probe_client, safe_get
from newsradar.research.probes.schema import (
    AcquisitionProbeOutcome,
    AcquisitionProbeSample,
    probe_result,
    public_probe_url,
    with_http_evidence,
)
from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition

from ...test_source_schema import valid_source


def candidate(url: str, auth: str = "none") -> AcquisitionCandidate:
    return AcquisitionCandidate.model_validate(
        {
            "key": "safe-feed",
            "kind": "rss",
            "implementation": "feedparser",
            "officiality": "official",
            "authentication": auth,
            "roles": ["discovery"],
            "fields": ["title"],
            "limitations": [],
            "evidence": [url],
            "reviewed_at": "2026-07-12",
            "sample_status": "not_run",
            "decision": "supplement",
        }
    )


@pytest.mark.asyncio
async def test_private_ip_target_is_blocked_before_network() -> None:
    source = SourceDefinition.model_validate(valid_source())
    async with httpx.AsyncClient(trust_env=False) as client:
        result = await FeedResearchProbe(HttpPolicy(client)).probe(
            source, candidate("https://127.0.0.1/private")
        )
    assert result.outcome.value == "blocked"
    assert result.error_code == "unsafe_url"


@pytest.mark.asyncio
async def test_feed_with_login_auth_is_blocked_before_network() -> None:
    source = SourceDefinition.model_validate(valid_source())
    async with httpx.AsyncClient(trust_env=False) as client:
        result = await FeedResearchProbe(HttpPolicy(client)).probe(
            source, candidate("https://example.test/feed", "approval")
        )
    assert result.outcome.value == "blocked"
    assert result.error_code == "authentication_required"


def test_sample_canonical_url_removes_query_and_fragment_and_rejects_userinfo() -> None:
    sample = AcquisitionProbeSample(canonical_url="https://example.test/post?token=secret#part")

    assert sample.canonical_url == "https://example.test/post"
    with pytest.raises(ValueError, match="credentialed_url"):
        AcquisitionProbeSample(canonical_url="https://user:pass@example.test/post")


@pytest.mark.asyncio
async def test_upstream_set_cookie_is_discarded_before_the_next_safe_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        headers = {"set-cookie": "tracking=discarded; Path=/"} if len(requests) == 1 else {}
        return httpx.Response(200, headers=headers, text="ok")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, trust_env=False, follow_redirects=False
    ) as client:
        policy = HttpPolicy(client)
        source_candidate = candidate("https://example.test/page")
        await safe_get(policy, source_candidate, "https://example.test/robots.txt")
        await safe_get(policy, source_candidate, "https://example.test/page")

        assert not client.cookies

    assert len(requests) == 2
    assert all("Cookie" not in request.headers for request in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "api_key=secret",
        "auth=secret",
        "access%5Ftoken=secret",
        "%74oken=secret",
        "token",
        "token=",
    ],
)
async def test_sensitive_query_is_blocked_before_any_probe_request(query: str) -> None:
    source = SourceDefinition.model_validate(valid_source())
    unsafe_candidate = candidate(f"https://example.test/feed?{query}")
    with pytest.raises(ValueError, match="sensitive_query"):
        public_probe_url(unsafe_candidate)

    async with httpx.AsyncClient(trust_env=False) as client:
        result = await FeedResearchProbe(HttpPolicy(client)).probe(source, unsafe_candidate)
    assert result.outcome.value == "blocked"
    assert result.error_code == "unsafe_url"


@pytest.mark.asyncio
async def test_cookie_jar_is_blocked_before_building_a_probe_request() -> None:
    source = SourceDefinition.model_validate(valid_source())
    requests = []

    async def responder(request):
        requests.append(request)
        return httpx.Response(200, text="<rss><channel /></rss>")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(responder), trust_env=False, cookies={"session": "secret"}
    ) as client:
        result = await FeedResearchProbe(HttpPolicy(client)).probe(
            source, candidate("https://example.test/feed")
        )

    assert result.outcome.value == "blocked"
    assert result.error_code == "unsafe_url"
    assert requests == []


@pytest.mark.asyncio
async def test_manual_client_with_trust_env_is_rejected_before_request() -> None:
    source = SourceDefinition.model_validate(valid_source())
    requests = []

    async def responder(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="<rss><channel /></rss>")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(responder), trust_env=True, follow_redirects=False
    ) as client:
        result = await FeedResearchProbe(HttpPolicy(client)).probe(
            source, candidate("https://example.test/feed")
        )

    assert result.outcome.value == "blocked"
    assert result.error_code == "unsafe_url"
    assert requests == []


@pytest.mark.asyncio
async def test_factory_client_with_trust_env_uses_safe_mock_transport_path() -> None:
    client = new_safe_probe_client()
    requests = []

    async def responder(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="ok")

    client._transport = httpx.MockTransport(responder)  # noqa: SLF001
    try:
        response = await safe_get(
            HttpPolicy(client), candidate("https://example.test/feed"), "https://example.test/feed"
        )
    finally:
        await client.aclose()

    assert response.status_code == 200
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_sensitive_query_in_redirect_location_is_blocked_before_following() -> None:
    source = SourceDefinition.model_validate(valid_source())
    requests = []

    async def responder(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "/next?token=secret"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(responder), trust_env=False
    ) as client:
        result = await FeedResearchProbe(HttpPolicy(client)).probe(
            source, candidate("https://example.test/feed")
        )

    assert result.outcome.value == "blocked"
    assert result.error_code == "unsafe_url"
    assert requests == ["https://example.test/feed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["/next?token", "/next?token=", "/next?%74oken=secret"])
async def test_sensitive_query_in_every_redirect_form_stops_before_next_request(
    location: str,
) -> None:
    source = SourceDefinition.model_validate(valid_source())
    requests = []

    async def responder(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": location})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(responder), trust_env=False
    ) as client:
        result = await FeedResearchProbe(HttpPolicy(client)).probe(
            source, candidate("https://example.test/feed")
        )

    assert result.outcome.value == "blocked"
    assert result.error_code == "unsafe_url"
    assert requests == ["https://example.test/feed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["X-Context", "X-Foo"])
async def test_probe_request_does_not_inherit_caller_default_headers(name: str) -> None:
    source = SourceDefinition.model_validate(valid_source())
    requests = []

    async def responder(request):
        requests.append(request)
        return httpx.Response(200, text="<rss><channel /></rss>")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(responder), trust_env=False, headers={name: "Bearer secret"}
    ) as client:
        result = await FeedResearchProbe(HttpPolicy(client)).probe(
            source, candidate("https://example.test/feed")
        )

    assert result.outcome.value == "partial"
    assert requests[0].headers.get(name) is None
    assert requests[0].headers["user-agent"] == "NewsCodexResearchProbe/0.1"
    assert requests[0].headers["accept"] == (
        "application/json, application/feed+json, application/xml, text/xml"
    )


@pytest.mark.asyncio
async def test_custom_async_http_transport_proxy_is_rejected_before_request() -> None:
    source = SourceDefinition.model_validate(valid_source())
    transport = httpx.AsyncHTTPTransport(proxy="http://127.0.0.1:9")
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        result = await FeedResearchProbe(HttpPolicy(client)).probe(
            source, candidate("https://example.test/feed")
        )

    assert result.outcome.value == "blocked"
    assert result.error_code == "unsafe_url"


def test_malicious_response_headers_are_absent_from_result_dump() -> None:
    source = SourceDefinition.model_validate(valid_source())
    item = candidate("https://example.test/feed")
    response = httpx.Response(
        200,
        headers={
            "etag": '"token=secret"',
            "last-modified": "https://example.test/last-modified?token=secret",
            "cache-control": "max-age=60, token=secret",
            "x-ratelimit-remaining": "12",
        },
        request=httpx.Request("GET", "https://example.test/feed"),
    )
    result = with_http_evidence(
        probe_result(source, item, AcquisitionProbeOutcome.SUCCEEDED, "ok"), response, item
    )

    dumped = repr(result.model_dump(mode="json"))
    assert result.etag is None
    assert result.last_modified is None
    assert result.cache_control is None
    assert result.rate_limit_remaining == 12
    assert "secret" not in dumped
    assert "https://example.test/last-modified" not in dumped
