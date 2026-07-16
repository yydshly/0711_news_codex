from pathlib import Path
from types import SimpleNamespace

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


def test_added_evidence_sources_are_fetchable_with_matching_success_probes() -> None:
    from newsradar.sources.yaml_loader import load_source_tree
    from newsradar.waves.loader import load_wave_profile
    from newsradar.waves.planning import build_wave_plan

    profile = load_wave_profile(Path("wave_profiles/high-value-ai-tech.yaml"))
    sources = load_source_tree(Path("sources"))
    added = [source for source in sources if source.id in ADDED_EVIDENCE_SOURCE_IDS]
    probes = {
        source.id: SimpleNamespace(
            access_kind=source.access_methods[0].kind.value,
            outcome="success",
        )
        for source in added
    }

    plan = build_wave_plan(profile, sources, probes, configured_credentials=set())
    by_id = {member.source_id: member for member in plan.members}

    assert all(by_id[source_id].fetchable for source_id in ADDED_EVIDENCE_SOURCE_IDS)
    assert all("evidence" in by_id[source_id].roles for source_id in ADDED_EVIDENCE_SOURCE_IDS)


def test_persisted_probe_snapshot_can_make_a_wave_member_fetchable() -> None:
    from datetime import UTC, datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from newsradar.db.models import Base
    from newsradar.sources.probes.base import ProbeOutcome, ProbeResult, ProbeSample
    from newsradar.sources.repository import SourceRepository
    from newsradar.sources.yaml_loader import load_source_tree
    from newsradar.waves.planning import build_wave_plan
    from newsradar.waves.schema import WaveProfile

    source = next(
        item for item in load_source_tree(Path("sources")) if item.id == "hackernews-top"
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    finished_at = datetime(2026, 7, 16, tzinfo=UTC)

    with Session(engine) as session:
        repository = SourceRepository(session)
        repository.sync([source])
        repository.save_probe_result(
            ProbeResult(
                source_id=source.id,
                access_kind="public_api",
                access_url=str(source.access_methods[0].url),
                outcome=ProbeOutcome.SUCCESS,
                started_at=finished_at,
                finished_at=finished_at,
                sample_count=1,
                field_completeness=1.0,
                samples=[
                    ProbeSample(
                        external_id="1",
                        title="OpenAI launches a model",
                        canonical_url="https://news.ycombinator.com/item?id=1",
                    )
                ],
                suggested_status="candidate",
                reason="ok",
            )
        )
        probes = repository.latest_probe_snapshots([source.id])

    profile = WaveProfile(
        id="probe-integration",
        name="Probe integration",
        window_hours=24,
        trend_days=7,
        required_roles=("discovery",),
        source_ids=(source.id,),
    )
    plan = build_wave_plan(profile, [source], probes, configured_credentials=set())

    assert plan.fetchable_ids == frozenset({source.id})


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
    assert members["openai-youtube"].blocked_reason == "missing_credentials"
    assert members["hackernews-top"].fetchable is True
    assert members["universe-ap-2"].fetchable is False
    assert members["universe-ap-2"].blocked_reason == "indirect_access"
    assert plan.digest == build_wave_plan(profile, list(reversed(sources)), probes, set()).digest


def test_source_availability_blocks_take_precedence_over_missing_probe() -> None:
    from newsradar.sources.yaml_loader import load_source_tree
    from newsradar.waves.loader import load_wave_profile
    from newsradar.waves.planning import build_wave_plan

    profile = load_wave_profile(Path("wave_profiles/high-value-ai-tech.yaml"))
    plan = build_wave_plan(profile, load_source_tree(Path("sources")), {}, set())
    members = {member.source_id: member for member in plan.members}

    assert members["openai-youtube"].blocked_reason == "missing_credentials"
    assert members["anthropic-newsroom"].blocked_reason == "requires_approval"


def test_requires_credentials_source_unlocks_with_configured_or_public_probed_method() -> None:
    from newsradar.sources.yaml_loader import load_source_tree
    from newsradar.waves.loader import load_wave_profile
    from newsradar.waves.planning import build_wave_plan

    profile = load_wave_profile(Path("wave_profiles/high-value-ai-tech.yaml"))
    sources = load_source_tree(Path("sources"))
    rest_probe = {"openai-youtube": SimpleNamespace(outcome="success", access_kind="rest_api")}
    atom_probe = {"openai-youtube": SimpleNamespace(outcome="success", access_kind="atom")}

    configured = build_wave_plan(
        profile, sources, rest_probe, configured_credentials={"YOUTUBE_API_KEY"}
    )
    public_fallback = build_wave_plan(
        profile, sources, atom_probe, configured_credentials=set()
    )
    configured_member = {member.source_id: member for member in configured.members}
    fallback_member = {member.source_id: member for member in public_fallback.members}

    assert configured_member["openai-youtube"].fetchable is True
    assert configured_member["openai-youtube"].blocked_reason is None
    assert fallback_member["openai-youtube"].fetchable is True
    assert fallback_member["openai-youtube"].blocked_reason is None
