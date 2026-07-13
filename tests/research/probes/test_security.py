import httpx
import pytest

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.research.probes.feed import FeedResearchProbe
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
@pytest.mark.parametrize(
    "query", ["api_key=secret", "auth=secret", "access%5Ftoken=secret", "%74oken=secret"],
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
