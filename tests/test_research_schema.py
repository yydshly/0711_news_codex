import pytest
from pydantic import ValidationError

from newsradar.sources.schema import (
    AcquisitionCandidate,
    ResearchStatus,
    SourceDefinition,
)


def legacy_source_payload() -> dict:
    return {
        "id": "anthropic-news",
        "name": "Anthropic News",
        "status": "candidate",
        "nature": "first_party",
        "roles": ["discovery", "evidence"],
        "language": "en",
        "topics": ["foundation_models", "agents"],
        "authority_score": 5,
        "poll_interval_minutes": 60,
        "access_methods": [
            {
                "kind": "rss",
                "url": "https://www.anthropic.com/news/rss.xml",
                "priority": 1,
            }
        ],
        "expected_fields": ["title", "canonical_url", "published_at", "summary"],
        "risk": {
            "terms": 1,
            "authentication": 0,
            "stability": 2,
            "data_quality": 1,
            "operating_cost": 0,
        },
    }


def test_legacy_source_defaults_to_needs_research() -> None:
    source = SourceDefinition.model_validate(legacy_source_payload())

    assert source.research.status == ResearchStatus.NEEDS_RESEARCH


def test_verified_source_requires_wanted_information_primary_and_evidence() -> None:
    payload = legacy_source_payload() | {
        "research": {"status": "verified", "wanted_information": []}
    }

    with pytest.raises(ValidationError):
        SourceDefinition.model_validate(payload)


def test_login_cookie_candidate_must_be_rejected() -> None:
    with pytest.raises(ValidationError):
        AcquisitionCandidate.model_validate(
            {
                "key": "page-cookie",
                "kind": "html",
                "implementation": "browser-session",
                "officiality": "unofficial_library",
                "authentication": "login_cookie",
                "roles": ["content"],
                "fields": ["content"],
                "limitations": ["requires_login"],
                "evidence": ["https://example.test/terms"],
                "reviewed_at": "2026-07-12",
                "sample_status": "blocked",
                "decision": "primary",
            }
        )


def test_candidate_rejects_browser_session_implementation() -> None:
    with pytest.raises(ValidationError):
        AcquisitionCandidate.model_validate(
            {
                "key": "page-browser",
                "kind": "html",
                "implementation": "browser-session",
                "officiality": "official",
                "authentication": "none",
                "roles": ["content"],
                "fields": ["content"],
                "limitations": [],
                "evidence": ["https://example.test/terms"],
                "reviewed_at": "2026-07-12",
                "sample_status": "blocked",
                "decision": "rejected",
            }
        )


def test_candidate_rejects_embedded_url_credentials() -> None:
    with pytest.raises(ValidationError):
        AcquisitionCandidate.model_validate(
            {
                "key": "official-feed",
                "kind": "rss",
                "implementation": "feedparser",
                "officiality": "official",
                "authentication": "none",
                "roles": ["content"],
                "fields": ["content"],
                "limitations": [],
                "evidence": ["https://user:secret@example.test/feed-docs"],
                "reviewed_at": "2026-07-12",
                "sample_status": "succeeded",
                "decision": "primary",
            }
        )


def test_verified_source_requires_a_fallback_or_documented_reason() -> None:
    payload = legacy_source_payload() | {
        "research": {
            "status": "verified",
            "wanted_information": ["content"],
            "candidates": [
                {
                    "key": "official-feed",
                    "kind": "rss",
                    "implementation": "feedparser",
                    "officiality": "official",
                    "authentication": "none",
                    "roles": ["content"],
                    "fields": ["content"],
                    "limitations": [],
                    "evidence": ["https://example.test/feed-docs"],
                    "reviewed_at": "2026-07-12",
                    "sample_status": "succeeded",
                    "decision": "primary",
                }
            ],
        }
    }

    with pytest.raises(ValidationError):
        SourceDefinition.model_validate(payload)


def test_verified_source_requires_explicit_purpose_and_risk_conclusion() -> None:
    payload = legacy_source_payload() | {
        "research": {
            "status": "verified",
            "wanted_information": ["content"],
            "no_fallback_reason": "官方 RSS 已满足所需信息。",
            "candidates": [
                {
                    "key": "official-feed",
                    "kind": "rss",
                    "implementation": "feedparser",
                    "officiality": "official",
                    "authentication": "none",
                    "roles": ["content"],
                    "fields": ["content"],
                    "limitations": [],
                    "evidence": ["https://example.test/feed-docs"],
                    "reviewed_at": "2026-07-12",
                    "sample_status": "succeeded",
                    "decision": "primary",
                }
            ],
        }
    }

    with pytest.raises(ValidationError):
        SourceDefinition.model_validate(payload)


def test_verified_source_requires_primary_candidate_own_sample() -> None:
    payload = legacy_source_payload() | {
        "research": {
            "status": "verified",
            "purpose": "收集官方新闻正文。",
            "risk_conclusion": "公开 RSS 风险可接受。",
            "wanted_information": ["content"],
            "no_fallback_reason": "官方 RSS 已满足所需信息。",
            "candidates": [
                {
                    "key": "primary-feed",
                    "kind": "rss",
                    "implementation": "feedparser",
                    "officiality": "official",
                    "authentication": "none",
                    "roles": ["content"],
                    "fields": ["content"],
                    "limitations": [],
                    "evidence": ["https://example.test/primary-docs"],
                    "reviewed_at": "2026-07-12",
                    "sample_status": "failed",
                    "decision": "primary",
                },
                {
                    "key": "supplement-feed",
                    "kind": "rss",
                    "implementation": "feedparser",
                    "officiality": "official",
                    "authentication": "none",
                    "roles": ["metadata"],
                    "fields": ["published_at"],
                    "limitations": [],
                    "evidence": ["https://example.test/supplement-docs"],
                    "reviewed_at": "2026-07-12",
                    "sample_status": "partial",
                    "decision": "supplement",
                },
            ],
        }
    }

    with pytest.raises(ValidationError):
        SourceDefinition.model_validate(payload)


def test_verified_source_accepts_primary_sample_evidence_and_fallback_reason() -> None:
    payload = legacy_source_payload() | {
        "research": {
            "status": "verified",
            "purpose": "收集官方新闻正文。",
            "risk_conclusion": "公开 RSS 风险可接受。",
            "wanted_information": ["content"],
            "no_fallback_reason": "官方 RSS 已满足所需信息。",
            "candidates": [
                {
                    "key": "official-feed",
                    "kind": "rss",
                    "implementation": "feedparser",
                    "officiality": "official",
                    "authentication": "none",
                    "roles": ["content"],
                    "fields": ["content"],
                    "limitations": [],
                    "evidence": ["https://example.test/feed-docs"],
                    "reviewed_at": "2026-07-12",
                    "sample_status": "partial",
                    "decision": "primary",
                }
            ],
        }
    }

    source = SourceDefinition.model_validate(payload)

    assert source.research.status == ResearchStatus.VERIFIED
