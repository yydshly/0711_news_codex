from pathlib import Path

import pytest

ADDED_EVIDENCE_SOURCE_IDS = frozenset(
    {
        "google-ai-blog",
        "nvidia-developer-blog",
        "universe-cnbc-1",
        "universe-mit-tech-review-1",
        "universe-venturebeat-1",
        "universe-wired-1",
    }
)


def test_high_value_profile_has_exact_evidence_confirmation_scope() -> None:
    from newsradar.providers.schema import Availability, CoverageMode
    from newsradar.sources.yaml_loader import load_source_tree
    from newsradar.waves.loader import load_wave_profile

    profile = load_wave_profile(Path("wave_profiles/high-value-ai-tech.yaml"))
    sources = {source.id: source for source in load_source_tree(Path("sources"))}

    assert profile.id == "high-value-ai-tech"
    assert len(profile.source_ids) == 41
    assert len(set(profile.source_ids)) == 41
    assert set(profile.source_ids) <= set(sources)
    assert ADDED_EVIDENCE_SOURCE_IDS <= set(profile.source_ids)
    assert {"discovery", "engagement", "evidence", "context"} <= set(profile.required_roles)
    for source_id in ADDED_EVIDENCE_SOURCE_IDS:
        source = sources[source_id]
        assert source.availability is Availability.READY
        assert source.coverage_mode is CoverageMode.DIRECT
        assert "evidence" in {role.value for role in source.roles}
        assert source.ingestion is not None and source.ingestion.enabled is True
        assert source.access_methods


@pytest.mark.parametrize(
    "yaml_text, message",
    [
        ("id: duplicate\nid: second\n", "duplicate"),
        (
            "id: valid\nname: Valid\nwindow_hours: 24\ntrend_days: 7\n"
            "required_roles: [discovery]\nsource_ids: [hackernews-top]\nextra: no\n",
            "extra",
        ),
        (
            "id: valid\nname: Valid\nwindow_hours: 24\ntrend_days: 7\n"
            "required_roles: [discovery]\nsource_ids: [not-an-existing-source]\n",
            "Unknown source id",
        ),
        (
            "id: valid\nname: Valid\nwindow_hours: 24\ntrend_days: 7\n"
            "required_roles: [discovery]\nsource_ids: [hackernews-top, hackernews-top]\n",
            "duplicate source id",
        ),
    ],
)
def test_profile_loader_rejects_invalid_or_unaudited_yaml(
    tmp_path: Path, yaml_text: str, message: str
) -> None:
    from newsradar.waves.loader import load_wave_profile

    path = tmp_path / "profile.yaml"
    path.write_text(yaml_text, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_wave_profile(path)
