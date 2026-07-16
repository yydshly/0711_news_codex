from pathlib import Path

from newsradar.providers.schema import Availability, CoverageMode, ProviderCategory
from newsradar.providers.yaml_loader import load_provider_tree
from newsradar.sources.schema import SourceStatus
from newsradar.sources.yaml_loader import load_source_tree


def test_source_universe_meets_coverage_floor() -> None:
    providers = load_provider_tree(Path("providers"))
    sources = load_source_tree(Path("sources"))

    assert len(providers) >= 35
    assert len(sources) >= 120
    assert {provider.category for provider in providers} == set(ProviderCategory)
    assert {"x", "facebook", "instagram", "tiktok", "linkedin"} <= {
        provider.id for provider in providers
    }
    direct_free = [
        source
        for source in sources
        if source.coverage_mode == CoverageMode.DIRECT and source.availability == Availability.READY
    ]
    assert len(direct_free) >= 25


def test_every_universe_target_has_audited_identity_and_provider() -> None:
    providers = {provider.id for provider in load_provider_tree(Path("providers"))}
    sources = load_source_tree(Path("sources"))
    universe = [source for source in sources if source.provider_id != "independent"]

    assert universe
    for source in universe:
        assert source.provider_id in providers
        assert source.official_identity_url is not None
        assert source.reviewed_at is not None
        assert source.risk.evidence
        assert source.access_methods
        if len(source.access_methods) == 1:
            assert source.notes and "fallback" in source.notes.lower()


def test_restricted_platforms_are_visible_but_not_claimed_as_direct_ready() -> None:
    providers = {provider.id: provider for provider in load_provider_tree(Path("providers"))}

    for provider_id in ("x", "facebook", "instagram", "tiktok", "linkedin"):
        provider = providers[provider_id]
        assert provider.availability != Availability.READY
        assert provider.unlock_requirements


def test_coverage_closure_catalog_facts_are_explicit() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}

    youtube = sources["openai-youtube"]
    assert youtube.expected_fields == [
        "title",
        "canonical_url",
        "published_at",
        "summary",
    ]
    assert "engagement" in youtube.research.wanted_information
    assert youtube.availability is Availability.REQUIRES_CREDENTIALS
    assert youtube.status is SourceStatus.DEGRADED
    youtube_api = next(
        method for method in youtube.access_methods if method.kind.value == "rest_api"
    )
    assert str(youtube_api.url) == "https://www.googleapis.com/youtube/v3/channels"
    assert youtube_api.params == {"id": "UCXZCJLdBC09xxGZ6gcdrc6A"}
    assert youtube_api.auth_envs == ("YOUTUBE_API_KEY",)

    qwen = sources["qwen3-releases"]
    assert qwen.availability is Availability.UNAVAILABLE
    assert qwen.status is SourceStatus.DEGRADED
    assert qwen.unlock_requirements
    assert "Release" in qwen.unlock_requirements[0]
    assert str(qwen.official_identity_url) == "https://github.com/QwenLM/Qwen3"


def test_cognitive_revolution_uses_official_public_podcast_feed() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}
    providers = {provider.id: provider for provider in load_provider_tree(Path("providers"))}

    source = sources["universe-cognitive-revolution-1"]
    provider = providers["cognitive-revolution"]

    assert provider.availability is Availability.READY
    assert provider.auth_mode.value == "none"
    assert source.availability is Availability.READY
    assert source.coverage_mode is CoverageMode.DIRECT
    assert source.ingestion.enabled is True
    assert source.access_methods[0].kind.value == "rss"
    assert str(source.access_methods[0].url) == "https://feeds.megaphone.fm/RINTP3108857801"
    assert source.access_methods[0].params == {"limit": "20"}
    assert not source.access_methods[0].auth_envs
