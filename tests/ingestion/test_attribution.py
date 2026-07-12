from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from newsradar.db.models import Base, FetchRunRecord, RawItemRecord, SourceDefinitionRecord
from newsradar.ingestion.attribution import (
    Attribution,
    OriginResolutionStatus,
    resolve_evidence_role,
)
from newsradar.ingestion.repository import RawItemRepository
from newsradar.ingestion.schema import NormalizedRawItem
from newsradar.sources.schema import SourceDefinition


def source(nature: str, roles: list[str]) -> SourceDefinition:
    return SourceDefinition.model_validate(
        {
            "id": f"{nature.replace('_', '-')}-source",
            "name": "Source",
            "status": "active",
            "nature": nature,
            "roles": roles,
            "language": "en",
            "topics": ["technology"],
            "authority_score": 3,
            "poll_interval_minutes": 60,
            "access_methods": [
                {"kind": "rss", "url": "https://source.test/feed", "priority": 1}
            ],
            "expected_fields": ["title"],
            "risk": {
                "terms": 0,
                "authentication": 0,
                "stability": 0,
                "data_quality": 0,
                "operating_cost": 0,
            },
        }
    )


def attribution() -> Attribution:
    return Attribution(
        publisher_name="Publisher",
        publisher_url="https://publisher.test/article",
        discovery_url="https://discovery.test/item",
        resolution_status=OriginResolutionStatus.RESOLVED,
    )


def test_professional_media_retains_evidence_role() -> None:
    roles = resolve_evidence_role(
        source("professional_media", ["discovery", "evidence"]), attribution()
    )

    assert roles == ("discovery", "evidence")


@pytest.mark.parametrize("nature", ["aggregator", "social", "community"])
def test_aggregator_social_and_community_cannot_contribute_evidence(nature: str) -> None:
    roles = resolve_evidence_role(
        source(nature, ["discovery", "engagement", "evidence"]), attribution()
    )

    assert roles == ("discovery", "engagement")


def test_attribution_and_raw_item_contracts_are_immutable_and_strict() -> None:
    value = attribution()
    item = NormalizedRawItem(
        external_id="post-42",
        title="A post",
        canonical_url="https://publisher.test/article",
        item_kind="social_post",
        publisher_name=value.publisher_name,
        publisher_url=value.publisher_url,
        discovery_url=value.discovery_url,
        origin_resolution_status=value.resolution_status,
        author_account_id="123",
        author_handle="@publisher",
        thread_root_id="root-1",
        raw_payload={},
    )

    assert item.origin_resolution_status is OriginResolutionStatus.RESOLVED
    with pytest.raises((AttributeError, TypeError)):
        value.publisher_name = "Other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        NormalizedRawItem(
            external_id="post-42",
            title="A post",
            canonical_url="https://publisher.test/article",
            raw_payload={},
            unknown=True,
        )


def test_repository_persists_attribution_and_social_identity_fields() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            SourceDefinitionRecord(
                id="source",
                name="Source",
                nature="social",
                language="en",
                roles=[],
                topics=[],
                authority_score=1,
                poll_interval_minutes=60,
                expected_fields=[],
                definition_hash="0" * 64,
            )
        )
        session.flush()
        run = FetchRunRecord(source_id="source")
        session.add(run)
        session.flush()
        item = NormalizedRawItem(
            external_id="post-42",
            title="A post",
            canonical_url="https://publisher.test/article",
            published_at=datetime(2026, 7, 11, tzinfo=UTC),
            item_kind="social_post",
            publisher_name="Publisher",
            publisher_url="https://publisher.test/article",
            discovery_url="https://discovery.test/item",
            origin_resolution_status=OriginResolutionStatus.RESOLVED,
            author_account_id="123",
            author_handle="@publisher",
            thread_root_id="root-1",
            raw_payload={},
        )

        RawItemRepository(session).upsert(run.id, "source", item)
        record = session.scalar(select(RawItemRecord))

        assert record is not None
        assert (record.item_kind, record.publisher_name, record.publisher_url) == (
            "social_post", "Publisher", "https://publisher.test/article",
        )
        assert (record.discovery_url, record.origin_resolution_status) == (
            "https://discovery.test/item", "resolved",
        )
        assert (record.author_account_id, record.author_handle, record.thread_root_id) == (
            "123", "@publisher", "root-1",
        )
