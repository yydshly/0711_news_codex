from pathlib import Path

from newsradar.sources.schema import SourceNature
from newsradar.sources.yaml_loader import load_source_tree

MATRIX_IDS = {
    "universe-bbc-1",
    "universe-guardian-1",
    "universe-wired-1",
    "universe-the-verge-1",
    "universe-techcrunch-1",
    "gdelt-ai",
    "techmeme-feed",
    "google-news-ai",
    "hackernews-top",
    "bluesky-bsky",
    "mastodon-mastodon",
}


def test_enabled_open_source_matrix_has_direct_identity_endpoint_and_approval() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}
    matrix = {source_id: sources[source_id] for source_id in MATRIX_IDS}
    enabled_matrix = {
        source_id: source for source_id, source in matrix.items() if source_id != "gdelt-ai"
    }

    assert all(source.ingestion.enabled for source in enabled_matrix.values())
    assert all(source.ingestion.approved_at is not None for source in enabled_matrix.values())
    assert all(source.official_identity_url is not None for source in matrix.values())
    assert all(source.access_methods and source.risk.evidence for source in matrix.values())
    assert sum(s.nature is SourceNature.PROFESSIONAL_MEDIA for s in matrix.values()) >= 5
    assert sum(s.nature is SourceNature.AGGREGATOR for s in matrix.values()) >= 2
    social_or_community = sum(
        s.nature in {SourceNature.SOCIAL, SourceNature.COMMUNITY} for s in matrix.values()
    )
    assert social_or_community >= 3
    for source in matrix.values():
        assert source.roles
        assert source.risk.total >= 0
    assert matrix["gdelt-ai"].status.value == "degraded"
    assert matrix["gdelt-ai"].ingestion.enabled is False
