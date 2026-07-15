from pathlib import Path
from types import SimpleNamespace


def test_plan_separates_fetchable_and_blocked_without_reading_credentials() -> None:
    from newsradar.sources.yaml_loader import load_source_tree
    from newsradar.waves.loader import load_wave_profile
    from newsradar.waves.planning import build_wave_plan

    profile = load_wave_profile(Path("wave_profiles/high-value-ai-tech.yaml"))
    sources = load_source_tree(Path("sources"))
    probes = {
        source.id: SimpleNamespace(
            outcome="success", access_kind=source.access_methods[0].kind.value
        )
        for source in sources
    }

    plan = build_wave_plan(profile, sources, probes, configured_credentials={"YOUTUBE_API_KEY"})

    assert plan.fetchable
    assert all(member.definition_hash for member in plan.members)
    assert all(member.source_id not in plan.fetchable_ids for member in plan.blocked)


def test_plan_requires_ready_content_access_matching_probe_and_all_credentials() -> None:
    from newsradar.sources.yaml_loader import load_source_tree
    from newsradar.waves.loader import load_wave_profile
    from newsradar.waves.planning import build_wave_plan

    profile = load_wave_profile(Path("wave_profiles/high-value-ai-tech.yaml"))
    sources = load_source_tree(Path("sources"))
    probes = {
        source.id: SimpleNamespace(
            outcome="success", access_kind=source.access_methods[0].kind.value
        )
        for source in sources
    }
    probes["openai-youtube"] = SimpleNamespace(outcome="success", access_kind="rss")

    plan = build_wave_plan(profile, sources, probes, configured_credentials=set())
    members = {member.source_id: member for member in plan.members}

    assert members["openai-youtube"].fetchable is False
    assert members["openai-youtube"].blocked_reason == "probe_method_mismatch"
    assert members["hackernews-top"].fetchable is True
    assert members["universe-ap-2"].fetchable is False
    assert members["universe-ap-2"].blocked_reason == "indirect_access"
    assert plan.digest == build_wave_plan(profile, list(reversed(sources)), probes, set()).digest
