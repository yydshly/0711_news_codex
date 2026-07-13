import httpx
import pytest

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.research.probes.feed import FeedResearchProbe
from newsradar.research.probes.schema import AcquisitionProbeSample, public_probe_url
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
@pytest.mark.parametrize("query", ["api_key=secret", "auth=secret"])
async def test_sensitive_query_is_blocked_before_any_probe_request(query: str) -> None:
    source = SourceDefinition.model_validate(valid_source())
    unsafe_candidate = candidate(f"https://example.test/feed?{query}")
    with pytest.raises(ValueError, match="sensitive_query"):
        public_probe_url(unsafe_candidate)

    async with httpx.AsyncClient(trust_env=False) as client:
        result = await FeedResearchProbe(HttpPolicy(client)).probe(source, unsafe_candidate)
    assert result.outcome.value == "blocked"
    assert result.error_code == "unsafe_url"
