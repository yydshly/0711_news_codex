from __future__ import annotations

from pathlib import Path

from newsradar.providers.yaml_loader import load_provider_tree
from newsradar.sources.schema import (
    AcquisitionAuth,
    AcquisitionDecision,
    Officiality,
    ResearchStatus,
    SampleStatus,
)
from newsradar.sources.yaml_loader import load_source_tree

ROOT = Path(__file__).parents[2]


def test_catalog_has_explicit_research_state_and_verified_targets_are_complete() -> None:
    sources = load_source_tree(ROOT / "sources")

    assert sources
    assert all(source.research.status in ResearchStatus for source in sources)
    verified = [
        source for source in sources if source.research.status is ResearchStatus.VERIFIED
    ]
    assert verified
    for source in verified:
        primary = [
            candidate
            for candidate in source.research.candidates
            if candidate.decision is AcquisitionDecision.PRIMARY
        ]
        assert source.research.wanted_information
        assert source.research.conclusion
        assert primary
        assert all(candidate.evidence for candidate in primary)
        assert any(
            candidate.sample_status in {SampleStatus.SUCCEEDED, SampleStatus.PARTIAL}
            for candidate in primary
        )


def test_openai_youtube_keeps_four_acquisition_paths_distinct() -> None:
    source = next(
        source
        for source in load_source_tree(ROOT / "sources")
        if source.id == "openai-youtube"
    )
    candidates = {candidate.key: candidate for candidate in source.research.candidates}

    assert set(candidates) == {
        "youtube-atom",
        "youtube-data-api",
        "youtube-transcript-api",
        "yt-dlp-metadata",
    }
    assert candidates["youtube-atom"].authentication is AcquisitionAuth.NONE
    assert candidates["youtube-atom"].decision is AcquisitionDecision.PRIMARY
    assert candidates["youtube-data-api"].authentication is AcquisitionAuth.API_KEY
    assert candidates["youtube-data-api"].sample_status is SampleStatus.BLOCKED
    assert (
        candidates["youtube-transcript-api"].officiality
        is Officiality.UNOFFICIAL_LIBRARY
    )
    assert candidates["yt-dlp-metadata"].decision is AcquisitionDecision.MANUAL_ONLY


def test_restricted_social_providers_are_cataloged_without_direct_content_claim() -> None:
    providers = {
        provider.id: provider for provider in load_provider_tree(ROOT / "providers")
    }

    for provider_id in ("x", "linkedin", "tiktok"):
        provider = providers[provider_id]
        assert provider.availability.value != "ready"
        assert provider.unlock_requirements


def test_chinese_delivery_explains_boundaries_and_records_all_live_outcomes() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "reports/source-research-v3-acceptance.md").read_text(
        encoding="utf-8"
    )

    for phrase in (
        "Provider",
        "Target",
        "Wanted Information",
        "YouTube Atom",
        "YouTube Data API",
        "youtube-transcript-api",
        "HTML 研究",
        "最小权限",
    ):
        assert phrase in readme
    for outcome in ("成功", "部分成功", "凭据阻塞", "失败", "未运行"):
        assert outcome in acceptance
    assert "MiniMax" in acceptance
    assert "未调用" in acceptance
