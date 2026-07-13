import httpx
import pytest

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.research.probes.feed import FeedResearchProbe
from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition

from ...test_source_schema import valid_source


def _source() -> SourceDefinition:
    return SourceDefinition.model_validate(valid_source())


def _candidate(kind: str = "rss") -> AcquisitionCandidate:
    return AcquisitionCandidate.model_validate(
        {
            "key": "public-feed",
            "kind": kind,
            "implementation": "feedparser",
            "officiality": "official",
            "authentication": "none",
            "roles": ["discovery"],
            "fields": ["title"],
            "limitations": [],
            "evidence": ["https://example.test/feed.xml"],
            "reviewed_at": "2026-07-12",
            "sample_status": "not_run",
            "decision": "supplement",
        }
    )


@pytest.mark.asyncio
async def test_feed_reads_at_most_five_public_entries_without_credentials() -> None:
    xml = (
        "<rss><channel>"
        + "".join(f"<item><guid>{i}</guid><title>T{i}</title></item>" for i in range(7))
        + "</channel></rss>"
    )
    seen = []

    async def responder(request):
        seen.append(request.headers)
        return httpx.Response(200, text=xml)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(responder), trust_env=False
    ) as client:
        result = await FeedResearchProbe(HttpPolicy(client)).probe(_source(), _candidate(), 5)
    assert result.outcome.value == "succeeded"
    assert len(result.samples) == 5
    assert "cookie" not in {key.lower() for key in seen[0]}
