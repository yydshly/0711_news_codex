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
