from pathlib import Path

from newsradar.sources.yaml_loader import load_source_tree

DISCOVERY_SOURCE_IDS = {
    "universe-ai-snake-oil-2",
    "universe-ars-technica-2",
    "universe-bbc-2",
    "universe-cnbc-2",
    "universe-guardian-2",
    "universe-hard-fork-2",
    "universe-import-ai-2",
    "universe-interconnects-2",
    "universe-mit-tech-review-2",
    "universe-techcrunch-2",
    "universe-techmeme-2",
    "universe-the-verge-2",
    "universe-venturebeat-2",
    "universe-wired-2",
}


def test_stable_google_news_discovery_cohort_is_approved_for_ingestion() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}
    cohort = {source_id: sources[source_id] for source_id in DISCOVERY_SOURCE_IDS}

    assert all(source.ingestion.enabled for source in cohort.values())
    assert all(source.ingestion.approved_at is not None for source in cohort.values())
    assert all(source.availability.value == "ready" for source in cohort.values())
    assert all(source.coverage_mode.value == "indirect" for source in cohort.values())
    assert all("discovery" in source.roles for source in cohort.values())


def test_empty_latent_space_discovery_query_is_not_promoted() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}

    assert sources["universe-latent-space-2"].ingestion.enabled is False
