from pathlib import Path

from newsradar.sources.mixed_wave import MIXED_WAVE_GROUPS, MIXED_WAVE_SOURCE_IDS
from newsradar.sources.yaml_loader import load_source_tree


def test_high_value_mixed_wave_has_45_real_targets() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}

    assert len(MIXED_WAVE_SOURCE_IDS) == 45
    assert MIXED_WAVE_SOURCE_IDS <= sources.keys()
    assert set(MIXED_WAVE_GROUPS) == {
        "reddit",
        "youtube",
        "bluesky",
        "mastodon",
        "hackernews",
        "techmeme",
        "gdelt",
        "google_news",
        "professional_media",
    }
    assert all(
        sources[source_id].research.status.value != "placeholder"
        for source_id in MIXED_WAVE_SOURCE_IDS
    )


def test_wave_roles_do_not_treat_social_or_aggregators_as_evidence() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}

    for group in ("reddit", "bluesky", "mastodon", "techmeme", "gdelt", "google_news"):
        for source_id in MIXED_WAVE_GROUPS[group]:
            assert "evidence" not in {role.value for role in sources[source_id].roles}


def test_youtube_targets_have_fixed_channel_ids_and_atom_fallbacks() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}

    for source_id in MIXED_WAVE_GROUPS["youtube"]:
        source = sources[source_id]
        primary, fallback = source.access_methods[:2]
        assert str(primary.url) == "https://www.googleapis.com/youtube/v3/channels"
        assert primary.params.get("id")
        assert primary.auth_envs == ("YOUTUBE_API_KEY",)
        assert str(fallback.url) == "https://www.youtube.com/feeds/videos.xml"
        assert fallback.params == {"channel_id": primary.params["id"]}


def test_restricted_media_are_explicit_indirect_google_news_targets() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}
    restricted_ids = {
        "universe-reuters-2",
        "universe-ap-2",
        "universe-bloomberg-2",
        "universe-financial-times-2",
        "universe-wsj-2",
    }

    for source_id in restricted_ids:
        source = sources[source_id]
        assert source.availability.value == "ready"
        assert source.coverage_mode.value == "indirect"
        assert source.access_methods[0].kind.value == "rss"
        assert str(source.access_methods[0].url) == "https://news.google.com/rss/search"
        assert source.ingestion.enabled is True
def test_washington_post_uses_official_news_sitemap_with_rss_fallback() -> None:
    from pathlib import Path

    from newsradar.providers.yaml_loader import load_provider_tree
    from newsradar.sources.yaml_loader import load_source_tree

    providers = {item.id: item for item in load_provider_tree(Path("providers"))}
    sources = {item.id: item for item in load_source_tree(Path("sources"))}
    source = sources["universe-washington-post-1"]
    provider = providers[source.provider_id]

    assert provider.availability.value == "ready"
    assert provider.auth_mode.value == "none"
    assert source.availability.value == "ready"
    assert source.coverage_mode.value == "direct"
    assert source.ingestion.enabled is True
    assert source.ingestion.max_items_per_run == 20
    assert source.access_methods[0].kind.value == "sitemap"
    assert str(source.access_methods[0].url) == (
        "https://www.washingtonpost.com/sitemaps/news-sitemap.xml.gz"
    )
    assert source.access_methods[1].kind.value == "rss"
    assert str(source.access_methods[1].url) == (
        "https://feeds.washingtonpost.com/rss/business/technology"
    )
    assert source.research.status.value == "verified"


def test_discord_communities_remains_manual_until_concrete_authorized_target() -> None:
    from pathlib import Path

    from newsradar.providers.yaml_loader import load_provider_tree
    from newsradar.sources.yaml_loader import load_source_tree

    providers = {item.id: item for item in load_provider_tree(Path("providers"))}
    sources = {item.id: item for item in load_source_tree(Path("sources"))}
    provider = providers["discord"]
    source = sources["universe-discord-1"]

    assert provider.availability.value == "manual_only"
    assert source.availability.value == "manual_only"
    assert source.coverage_mode.value == "catalog_only"
    assert source.ingestion.enabled is False
    assert source.research.status.value == "needs_research"
    combined = " ".join(
        [
            source.research.conclusion or "",
            source.research.risk_conclusion or "",
            *source.unlock_requirements,
            *provider.unlock_requirements,
        ]
    ).lower()
    assert "blog" in combined
    assert "server" in combined
    assert "channel" in combined
    assert "administrator" in combined
    assert "bot" in combined


def test_validated_newsletters_use_shared_official_sitemap_ingestion() -> None:
    from pathlib import Path

    from newsradar.providers.yaml_loader import load_provider_tree
    from newsradar.sources.yaml_loader import load_source_tree

    sources = {item.id: item for item in load_source_tree(Path("sources"))}
    providers = {item.id: item for item in load_provider_tree(Path("providers"))}
    expected = {
        "universe-bens-bites-1": "https://www.bensbites.com/sitemap.xml",
        "universe-tldr-ai-1": "https://ai.tldr.tech/sitemap.xml",
    }

    for source_id, sitemap_url in expected.items():
        source = sources[source_id]
        assert providers[source.provider_id].availability.value == "ready"
        assert providers[source.provider_id].auth_mode.value == "none"
        assert source.availability.value == "ready"
        assert source.coverage_mode.value == "direct"
        assert source.ingestion.enabled is True
        assert source.access_methods[0].kind.value == "sitemap"
        assert str(source.access_methods[0].url) == sitemap_url
        assert source.research.status.value == "verified"
        assert source.research.candidates[0].kind.value == "sitemap"


def test_professional_media_use_shared_official_news_sitemaps() -> None:
    from pathlib import Path

    from newsradar.providers.yaml_loader import load_provider_tree
    from newsradar.sources.yaml_loader import load_source_tree

    sources = {item.id: item for item in load_source_tree(Path("sources"))}
    providers = {item.id: item for item in load_provider_tree(Path("providers"))}
    expected = {
        "universe-axios-1": "https://www.axios.com/sitemaps/news.xml",
        "universe-forbes-1": "https://www.forbes.com/news_sitemap.xml",
        "universe-fortune-1": "https://fortune.com/feed/googlenews/articles.xml",
        "universe-semafor-1": "https://www.semafor.com/sitemap-news.xml",
    }

    for source_id, sitemap_url in expected.items():
        source = sources[source_id]
        provider = providers[source.provider_id]
        assert provider.availability.value == "ready"
        assert provider.auth_mode.value == "none"
        assert source.availability.value == "ready"
        assert source.coverage_mode.value == "direct"
        assert source.ingestion.enabled is True
        assert source.ingestion.max_items_per_run == 20
        assert source.access_methods[0].kind.value == "sitemap"
        assert str(source.access_methods[0].url) == sitemap_url
        assert not source.access_methods[0].auth_envs
        assert source.access_methods[0].requires_manual_approval is False
        assert source.research.status.value == "verified"
        assert source.research.candidates[0].kind.value == "sitemap"
