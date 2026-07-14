from pathlib import Path

from newsradar.sources.yaml_loader import load_source_tree

COHORT_SOURCE_IDS = {
    "universe-ai-snake-oil-1",
    "universe-ars-technica-1",
    "arxiv-cs-cl",
    "arxiv-cs-dc",
    "arxiv-cs-lg",
    "arxiv-cs-se",
    "universe-cnbc-1",
    "google-ai-blog",
    "hackernews-new",
    "universe-hard-fork-1",
    "universe-import-ai-1",
    "microsoft-research",
    "universe-interconnects-1",
    "universe-latent-space-1",
    "universe-mit-tech-review-1",
    "nvidia-developer-blog",
    "universe-venturebeat-1",
}


def test_three_round_open_source_cohort_is_approved_for_ingestion() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}
    cohort = {source_id: sources[source_id] for source_id in COHORT_SOURCE_IDS}

    assert all(source.ingestion.enabled for source in cohort.values())
    assert all(source.ingestion.approved_at is not None for source in cohort.values())
    assert all(source.availability.value == "ready" for source in cohort.values())
    assert all(source.coverage_mode.value == "direct" for source in cohort.values())


def test_degraded_or_duplicate_sources_are_not_promoted_with_open_cohort() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}

    assert sources["gdelt-ai"].ingestion.enabled is False
    assert sources["universe-techmeme-1"].ingestion.enabled is False
