from pathlib import Path

import pytest


def test_high_value_profile_has_bounded_existing_targets() -> None:
    from newsradar.sources.yaml_loader import load_source_tree
    from newsradar.waves.loader import load_wave_profile

    profile = load_wave_profile(Path("wave_profiles/high-value-ai-tech.yaml"))
    source_catalog = load_source_tree(Path("sources"))

    assert profile.id == "high-value-ai-tech"
    assert 30 <= len(profile.source_ids) <= 50
    assert set(profile.source_ids) <= {source.id for source in source_catalog}
    assert {"discovery", "engagement", "evidence", "context"} <= set(profile.required_roles)


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
