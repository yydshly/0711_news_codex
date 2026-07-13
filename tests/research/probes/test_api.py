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
