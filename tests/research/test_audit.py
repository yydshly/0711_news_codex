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


def test_audit_keeps_universe_placeholder_as_warning() -> None:
    report = audit_source_catalog((), (_source(id="universe-social-1"),))

    assert report.status_counts == {"needs_research": 1}
    assert any(
        finding.code == "placeholder_target" and finding.severity == "warning"
        for finding in report.findings
    )


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
