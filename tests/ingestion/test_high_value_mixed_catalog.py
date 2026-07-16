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
def test_washington_post_primary_registers_official_public_rss_without_activation() -> None:
    from pathlib import Path

    from newsradar.sources.yaml_loader import load_source_tree

    source = next(
        item
        for item in load_source_tree(Path("sources"))
        if item.id == "universe-washington-post-1"
    )

    assert source.availability.value == "manual_only"
    assert source.ingestion.enabled is False
    assert source.access_methods[0].kind.value == "rss"
    assert str(source.access_methods[0].url) == (
        "https://feeds.washingtonpost.com/rss/business/technology"
    )
