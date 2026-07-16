from __future__ import annotations

from pathlib import Path

from newsradar.sources.yaml_loader import load_source_tree

PAIR_BASES = (
    "anthropic",
    "arxiv",
    "bluesky",
    "gdelt",
    "github",
    "google-ai",
    "google-news",
    "hackernews",
    "huggingface-papers",
    "mastodon",
    "npm",
    "nvidia",
    "openai",
    "openreview",
    "polymarket",
    "pypi",
    "sec-edgar",
    "semantic-scholar",
    "the-batch",
)


def test_duplicate_placeholder_pairs_have_one_canonical_discovery_target() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}

    for base in PAIR_BASES:
        duplicate = sources[f"universe-{base}-1"]
        canonical = sources[f"universe-{base}-2"]

        assert duplicate.research.status.value == "duplicate"
        assert canonical.research.status.value == "needs_research"
        assert not duplicate.ingestion.enabled
        assert not canonical.ingestion.enabled
        assert str(duplicate.access_methods[0].url) == str(canonical.access_methods[0].url)


def test_placeholder_resolution_reflects_expanded_mixed_source_catalog() -> None:
    sources = list(load_source_tree(Path("sources")))

    assert len(sources) == 187
    assert sum(source.ingestion.enabled for source in sources) == 83
