from __future__ import annotations

from newsradar.providers.schema import ProviderDefinition
from newsradar.research.audit import audit_source_catalog
from newsradar.sources.schema import ResearchStatus, SourceDefinition, SourceResearchProfile
from tests.test_provider_schema import valid_provider
from tests.test_source_schema import valid_source


def _provider() -> ProviderDefinition:
    return ProviderDefinition.model_validate(valid_provider())


def _source(**changes: object) -> SourceDefinition:
    payload = valid_source() | changes
    return SourceDefinition.model_validate(payload)


def _verified_research(kind: str = "rss") -> dict[str, object]:
    return {
        "status": "verified",
        "purpose": "收集公开资讯",
        "wanted_information": ["正文"],
        "risk_conclusion": "公开接口风险可接受",
        "no_fallback_reason": "首选方案足够",
        "candidates": [
            {
                "key": "primary-source",
                "kind": kind,
                "implementation": "feedparser" if kind == "rss" else "httpx",
                "officiality": "official",
                "authentication": "none",
                "roles": ["content"],
                "fields": ["content"],
                "limitations": [],
                "evidence": ["https://example.test/docs"],
                "reviewed_at": "2026-07-12",
                "sample_status": "succeeded",
                "decision": "primary",
            }
        ],
    }


def test_audit_does_not_treat_universe_id_as_placeholder() -> None:
    report = audit_source_catalog((), (_source(id="universe-social-1"),))

    assert report.status_counts == {"needs_research": 1}
    assert not any(finding.code == "placeholder_target" for finding in report.findings)


def test_audit_flags_explicit_placeholder_status() -> None:
    report = audit_source_catalog(
        (),
        (_source(id="real-placeholder", research={"status": "placeholder"}),),
    )

    assert [finding.code for finding in report.findings] == ["placeholder_target"]


def test_audit_flags_provider_homepage_as_generic_platform_target() -> None:
    provider = _provider()
    source = _source(
        provider_id=provider.id,
        official_identity_url=str(provider.homepage),
    )

    report = audit_source_catalog((provider,), (source,))

    assert any(finding.code == "generic_platform_target" for finding in report.findings)


def test_audit_flags_duplicate_official_identity_within_provider() -> None:
    provider = _provider()
    first = _source(provider_id=provider.id, official_identity_url="https://example.test/profile")
    second = _source(
        id="another-source",
        provider_id=provider.id,
        official_identity_url="https://example.test/profile",
    )

    report = audit_source_catalog((provider,), (first, second))

    assert [finding.code for finding in report.findings].count("duplicate_candidate") == 2


def test_audit_does_not_reopen_explicit_duplicate_as_pending_candidate() -> None:
    provider = _provider()
    duplicate = _source(
        provider_id=provider.id,
        official_identity_url="https://example.test/profile",
        research={"status": "duplicate"},
    )
    canonical = _source(
        id="canonical-source",
        provider_id=provider.id,
        official_identity_url="https://example.test/profile",
    )

    report = audit_source_catalog((provider,), (duplicate, canonical))

    assert not any(finding.code == "duplicate_candidate" for finding in report.findings)


def test_audit_does_not_confuse_direct_and_indirect_targets_with_same_provider_identity() -> None:
    provider = _provider()
    direct = _source(
        provider_id=provider.id,
        official_identity_url="https://example.test/profile",
    )
    indirect = _source(
        id="indirect-source",
        provider_id=provider.id,
        target_type="search_query",
        coverage_mode="indirect",
        official_identity_url="https://example.test/profile",
    )

    report = audit_source_catalog((provider,), (direct, indirect))

    assert not any(finding.code == "duplicate_candidate" for finding in report.findings)


def test_audit_reports_incomplete_verified_research_as_errors() -> None:
    source = _source()
    object.__setattr__(
        source,
        "research",
        SourceResearchProfile.model_construct(status=ResearchStatus.VERIFIED),
    )

    report = audit_source_catalog((), (source,))

    assert {finding.code for finding in report.findings} >= {
        "verified_missing_purpose",
        "verified_missing_wanted_information",
        "verified_missing_primary",
        "verified_missing_risk_conclusion",
        "verified_missing_fallback_reason",
    }


def test_audit_counts_only_verified_targets_as_real_coverage_and_separates_methods() -> None:
    verified = _source(research=_verified_research("public_api"))
    needs_research = _source(id="needs-research")
    placeholder = _source(id="placeholder", research={"status": "placeholder"})
    duplicate = _source(id="duplicate", research={"status": "duplicate"})
    retired = _source(id="retired", research={"status": "retired"})

    report = audit_source_catalog((), (verified, needs_research, placeholder, duplicate, retired))

    assert report.target_count == 2
    assert report.status_counts == {
        "verified": 1,
        "needs_research": 1,
        "placeholder": 1,
        "duplicate": 1,
        "retired": 1,
    }
    assert report.method_counts == {"public_api": 1}


def test_audit_report_keeps_immutable_target_snapshots() -> None:
    source = _source(research=_verified_research())
    report = audit_source_catalog((), (source,))

    object.__setattr__(source, "name", "已被篡改")

    assert report.targets[0].name != "已被篡改"
    assert report.targets[0].id == "anthropic-news"


def test_audit_counts_api_html_library_and_aggregator_separately() -> None:
    kinds = ("public_api", "html", "library", "aggregator")
    sources = tuple(
        _source(id=f"source-{index}", research=_verified_research(kind))
        for index, kind in enumerate(kinds, start=1)
    )

    report = audit_source_catalog((), sources)

    assert report.method_counts == {kind: 1 for kind in kinds}


def test_audit_counts_sources_by_nature() -> None:
    professional = _source(nature="professional_media")
    research = _source(id="research-source", nature="research")

    report = audit_source_catalog((), (professional, research))

    assert report.category_counts == {"professional_media": 1, "research": 1}
