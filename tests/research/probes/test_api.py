import httpx
import pytest

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.research.probes.api import ApiResearchProbe
from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition

from ...test_source_schema import valid_source


@pytest.mark.asyncio
async def test_oauth_api_is_blocked_without_sending_authorization() -> None:
    source = SourceDefinition.model_validate(valid_source())
    candidate = AcquisitionCandidate.model_validate(
        {
            "key": "oauth-api",
            "kind": "oauth_api",
            "implementation": "httpx",
            "officiality": "official",
            "authentication": "oauth",
            "roles": ["metadata"],
            "fields": ["title"],
            "limitations": [],
            "evidence": ["https://example.test/api"],
            "reviewed_at": "2026-07-12",
            "sample_status": "not_run",
            "decision": "manual_only",
        }
    )
    async with httpx.AsyncClient(trust_env=False) as client:
        result = await ApiResearchProbe(HttpPolicy(client)).probe(source, candidate)
    assert result.outcome.value == "blocked"
    assert result.error_code == "credential_required"


@pytest.mark.asyncio
async def test_public_api_records_http_evidence_and_returns_counted_samples() -> None:
    source = SourceDefinition.model_validate(valid_source())
    candidate = AcquisitionCandidate.model_validate(
        {
            "key": "public-api",
            "kind": "public_api",
            "implementation": "httpx",
            "officiality": "official",
            "authentication": "none",
            "roles": ["metadata"],
            "fields": ["title"],
            "limitations": [],
            "evidence": ["https://example.test/api"],
            "reviewed_at": "2026-07-12",
            "sample_status": "not_run",
            "decision": "manual_only",
        }
    )

    async def responder(request):
        return httpx.Response(
            200,
            headers={
                "etag": '"version-1"',
                "last-modified": "Sun, 12 Jul 2026 12:00:00 GMT",
                "cache-control": "max-age=60",
                "x-ratelimit-remaining": "7",
            },
            json={
                "items": [
                    {
                        "id": "one",
                        "title": "One",
                        "url": "https://example.test/one?token=secret#part",
                    },
                    {"id": "two", "title": "Two"},
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(responder), trust_env=False
    ) as client:
        result = await ApiResearchProbe(HttpPolicy(client)).probe(source, candidate)

    assert result.http_status == 200
    assert result.final_url == "https://example.test/api"
    assert result.etag == '"version-1"'
    assert result.last_modified == "Sun, 12 Jul 2026 12:00:00 GMT"
    assert result.latency_ms is not None
    assert result.rate_limit_remaining == 7
    assert result.sample_count == len(result.samples) == 2
    assert result.samples[0].canonical_url == "https://example.test/one"


@pytest.mark.asyncio
async def test_api_json_error_keeps_response_evidence() -> None:
    source = SourceDefinition.model_validate(valid_source())
    candidate = AcquisitionCandidate.model_validate(
        {
            "key": "public-api",
            "kind": "public_api",
            "implementation": "httpx",
            "officiality": "official",
            "authentication": "none",
            "roles": ["metadata"],
            "fields": ["title"],
            "limitations": [],
            "evidence": ["https://example.test/api"],
            "reviewed_at": "2026-07-12",
            "sample_status": "not_run",
            "decision": "manual_only",
        }
    )

    async def responder(request):
        return httpx.Response(200, headers={"etag": '"v1"'}, content=b"not json")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(responder), trust_env=False
    ) as client:
        result = await ApiResearchProbe(HttpPolicy(client)).probe(source, candidate)

    assert result.error_code == "JSONDecodeError"
    assert result.http_status == 200
    assert result.final_url == "https://example.test/api"
    assert result.etag == '"v1"'
    assert result.latency_ms is not None
