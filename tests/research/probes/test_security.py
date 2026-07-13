import httpx
import pytest

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.research.probes.feed import FeedResearchProbe
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


@pytest.mark.asyncio
async def test_real_hostname_is_blocked_when_dns_binding_cannot_be_proven() -> None:
    source = SourceDefinition.model_validate(valid_source())
    async with httpx.AsyncClient(trust_env=False) as client:
        result = await FeedResearchProbe(HttpPolicy(client)).probe(
            source, candidate("https://example.com/feed")
        )
    assert result.outcome.value == "blocked"
    assert result.error_code == "unsafe_url"
