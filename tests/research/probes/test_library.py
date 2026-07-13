import httpx
import pytest

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.research.probes.library import LibraryResearchProbe
from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition

from ...test_source_schema import valid_source


@pytest.mark.asyncio
async def test_library_probe_is_metadata_only_and_never_networks() -> None:
    source = SourceDefinition.model_validate(valid_source())
    candidate = AcquisitionCandidate.model_validate(
        {
            "key": "third-party-lib",
            "kind": "library",
            "implementation": "manual-review",
            "officiality": "unofficial_library",
            "authentication": "none",
            "roles": ["metadata"],
            "fields": ["title"],
            "limitations": [],
            "evidence": ["https://example.test/lib"],
            "reviewed_at": "2026-07-12",
            "sample_status": "not_run",
            "decision": "manual_only",
        }
    )
    async with httpx.AsyncClient(trust_env=False) as client:
        result = await LibraryResearchProbe(HttpPolicy(client)).probe(source, candidate)
    assert result.decision == "manual_only"
    assert result.metadata["network_used"] is False
