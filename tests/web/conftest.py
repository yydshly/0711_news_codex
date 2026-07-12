from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from newsradar.db.models import (
    Base,
    ProviderDefinitionRecord,
    ProviderProbeRunRecord,
    SourceAccessMethodRecord,
    SourceDefinitionRecord,
    SourceProbeRunRecord,
    SourceRiskAssessmentRecord,
)

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


def _provider(
    provider_id: str,
    name: str,
    category: str,
    cost_tier: str,
    availability: str,
) -> ProviderDefinitionRecord:
    return ProviderDefinitionRecord(
        id=provider_id,
        name=name,
        category=category,
        homepage=f"https://{provider_id}.example/",
        docs_url=f"https://{provider_id}.example/docs",
        terms_url=f"https://{provider_id}.example/terms",
        auth_mode="none" if cost_tier == "free" else "paid",
        cost_tier=cost_tier,
        availability=availability,
        capabilities=["search"],
        required_env=[] if cost_tier == "free" else ["X_API_KEY"],
        reviewed_at=date(2026, 7, 10),
        evidence=[f"https://{provider_id}.example/evidence"],
        unlock_requirements=[] if cost_tier == "free" else ["购买 API 访问"],
        notes=f"{name} provider",
        definition_hash=f"{provider_id}-hash",
    )


def _target(
    source_id: str,
    name: str,
    provider_id: str,
    target_type: str,
    coverage_mode: str,
    availability: str,
) -> SourceDefinitionRecord:
    return SourceDefinitionRecord(
        id=source_id,
        name=name,
        provider_id=provider_id,
        target_type=target_type,
        availability=availability,
        coverage_mode=coverage_mode,
        official_identity_url=f"https://{provider_id}.example/{source_id}",
        reviewed_at=date(2026, 7, 10),
        unlock_requirements=[] if availability == "ready" else ["购买 API 访问"],
        status="candidate",
        nature="first_party" if provider_id == "github" else "social",
        language="en",
        roles=["discovery"],
        topics=["ai"],
        authority_score=80,
        poll_interval_minutes=60,
        expected_fields=["title", "canonical_url"],
        notes=f"{name} target",
        definition_hash=f"{source_id}-hash",
    )


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                _provider("github", "GitHub", "research_developer", "free", "ready"),
                _provider("x", "X", "social_community", "paid", "requires_payment"),
            ]
        )
        targets = [
            _target(
                "github-openai-python",
                "OpenAI Python",
                "github",
                "publisher_feed",
                "direct",
                "ready",
            ),
            _target("search-ai", "AI Search", "github", "search_query", "indirect", "ready"),
            _target("x-openai", "OpenAI on X", "x", "account", "direct", "requires_payment"),
        ]
        session.add_all(targets)
        session.flush()

        for index, target in enumerate(targets, start=1):
            session.add(
                SourceAccessMethodRecord(
                    source_id=target.id,
                    kind="rss" if target.provider_id == "github" else "rest_api",
                    url=f"https://feeds.example/{target.id}",
                    priority=1,
                    requires_manual_approval=False,
                    auth_env=None if target.provider_id == "github" else "X_API_KEY",
                    headers={"Authorization": "secret-token-value"},
                    params={},
                )
            )
            session.add(
                SourceRiskAssessmentRecord(
                    source_id=target.id,
                    terms=index,
                    authentication=index,
                    stability=index,
                    data_quality=index,
                    operating_cost=index,
                    total=index * 5,
                    evidence=[f"https://risk.example/{target.id}"],
                    hard_block_reason=("payment required" if target.provider_id == "x" else None),
                    assessed_at=NOW - timedelta(days=index),
                )
            )

        for offset in range(3):
            finished_at = NOW - timedelta(hours=offset)
            session.add(
                SourceProbeRunRecord(
                    source_id="github-openai-python",
                    access_kind="rss",
                    access_url="https://feeds.example/github-openai-python",
                    outcome="success",
                    started_at=finished_at - timedelta(seconds=1),
                    finished_at=finished_at,
                    latency_ms=10.0 + offset,
                    http_status=200,
                    final_url="https://feeds.example/github-openai-python",
                    response_headers={"set-cookie": "must-not-leak"},
                    metrics={"field_completeness": 1.0 - offset / 10},
                    schema_fingerprint=f"schema-{offset}",
                    suggested_status="active",
                    reason="ok",
                    error_code=None,
                )
            )

        session.add(
            ProviderProbeRunRecord(
                provider_id="x",
                probe_type="capability",
                outcome="blocked",
                availability="requires_payment",
                reason="payment required",
                checked_at=NOW - timedelta(minutes=30),
                latency_ms=20.0,
                http_status=403,
                evidence_url="https://x.example/evidence",
            )
        )
        session.commit()
        yield session


@pytest.fixture
def query_service(db_session: Session):
    from newsradar.web.queries import DashboardQueryService

    return DashboardQueryService(db_session)
