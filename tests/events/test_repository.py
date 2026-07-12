from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    EventCandidateItemRecord,
    EventItemRecord,
    EventRecord,
    EventVersionRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.repository import EventRepository
from newsradar.events.schema import (
    CandidateCluster,
    EventStatus,
    ProcessingStage,
    PublishedEvent,
    ScoreBreakdown,
)


def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def raw_item(db: Session) -> RawItemRecord:
    db.add(
        SourceDefinitionRecord(
            id="source",
            name="Source",
            nature="publisher",
            language="en",
            roles=[],
            topics=[],
            authority_score=1,
            poll_interval_minutes=60,
            expected_fields=[],
            definition_hash="hash",
        )
    )
    item = RawItemRecord(
        source_id="source",
        external_id="item",
        canonical_url="https://example.test/item",
        payload={},
    )
    db.add(item)
    db.commit()
    return item


def published_event(**changes: object) -> PublishedEvent:
    data: dict[str, object] = {
        "canonical_key": "release",
        "status": EventStatus.EMERGING,
        "score": ScoreBreakdown(
            ai_relevance=0,
            source_coverage=0,
            source_authority=0,
            recency=0,
            engagement_velocity=0,
            novelty=0,
            importance=0,
            credibility=0,
            heat=0,
            rule_version="score-v1",
            reasons=(),
        ),
    }
    data.update(changes)
    return PublishedEvent(**data)


def test_stage_record_is_idempotent() -> None:
    with session() as db:
        item = raw_item(db)
        repository = EventRepository(db)

        first = repository.record_stage(item.id, ProcessingStage.RELEVANCE, "relevance-v1")
        second = repository.record_stage(item.id, ProcessingStage.RELEVANCE, "relevance-v1")
        db.commit()

        assert first.id == second.id


def test_claim_statement_uses_conditional_live_lease_guard() -> None:
    with session() as db:
        statement = EventRepository(db)._claim_statement(
            event_id=1,
            operation_id=2,
            lease_until=datetime.now(UTC) + timedelta(minutes=1),
        )

        compiled = str(statement.compile(dialect=postgresql.dialect()))

        assert "UPDATE events" in compiled
        assert "lease_expires_at" in compiled


def test_candidate_upsert_replaces_membership_and_updates_timestamp() -> None:
    with session() as db:
        first_item = raw_item(db)
        second_item = RawItemRecord(
            source_id="source",
            external_id="item-2",
            canonical_url="https://example.test/item-2",
            payload={},
        )
        db.add(second_item)
        db.commit()
        repository = EventRepository(db)
        candidate = repository.upsert_candidate(
            CandidateCluster(candidate_key="release", title="Initial"), "cluster-v1"
        )
        candidate.updated_at = datetime(2000, 1, 1)
        repository.replace_candidate_items(candidate.id, (first_item.id,))
        db.commit()

        updated = repository.upsert_candidate(
            CandidateCluster(candidate_key="release", title="Updated"), "cluster-v1"
        )
        repository.replace_candidate_items(updated.id, (second_item.id,))
        db.commit()

        assert updated.id == candidate.id
        assert updated.updated_at > datetime(2000, 1, 1)
        membership = db.scalars(select(EventCandidateItemRecord)).all()
        assert [item.raw_item_id for item in membership] == [second_item.id]


def test_event_update_publishing_claim_and_release_are_durable() -> None:
    with session() as db:
        item = raw_item(db)
        repository = EventRepository(db)
        initial = PublishedEvent(canonical_key="release", status=EventStatus.EMERGING)
        event = repository.create_or_update_event(initial)
        event.updated_at = datetime(2000, 1, 1)
        db.commit()

        updated = repository.create_or_update_event(
            PublishedEvent(
                event_id=event.id,
                canonical_key="release",
                status=EventStatus.CONFIRMED,
                source_item_ids=(item.id,),
            )
        )
        repository.publish_complete_event(published_event(), operation_id=1)
        repository.publish_complete_event(
            published_event(status=EventStatus.CONFIRMED, source_item_ids=(item.id,)),
            operation_id=1,
        )
        db.commit()

        assert updated.updated_at > datetime(2000, 1, 1)
        versions = db.scalars(select(EventVersionRecord)).all()
        assert [version.version_number for version in versions] == [1, 2]
        assert db.get(EventRecord, updated.id).current_version_number == 2  # type: ignore[union-attr]
        assert db.scalars(select(EventItemRecord)).all()[0].removed_version_number is None
        assert repository.claim_event(updated.id, 1, datetime.now(UTC) + timedelta(minutes=1))
        assert not repository.claim_event(updated.id, 2, datetime.now(UTC) + timedelta(minutes=1))
        assert not repository.release_event(updated.id, 2)
        assert repository.release_event(updated.id, 1)
        assert db.get(EventRecord, updated.id).lease_expires_at is None  # type: ignore[union-attr]


def test_repeated_stage_and_candidate_upserts_use_unique_keys() -> None:
    with session() as db:
        item = raw_item(db)
        repository = EventRepository(db)

        first_stage = repository.record_stage(item.id, ProcessingStage.RELEVANCE, "v1")
        second_stage = repository.record_stage(item.id, ProcessingStage.RELEVANCE, "v1")
        first_candidate = repository.upsert_candidate(CandidateCluster(candidate_key="key"), "v1")
        second_candidate = repository.upsert_candidate(CandidateCluster(candidate_key="key"), "v1")

        assert first_stage.id == second_stage.id
        assert first_candidate.id == second_candidate.id


def test_publishing_closes_removed_memberships_and_readds_as_new_rows() -> None:
    with session() as db:
        first = raw_item(db)
        second = RawItemRecord(
            source_id="source",
            external_id="item-2",
            canonical_url="https://example.test/item-2",
            payload={},
        )
        db.add(second)
        db.commit()
        repository = EventRepository(db)
        repository.create_or_update_event(
            PublishedEvent(canonical_key="release", status=EventStatus.EMERGING)
        )

        repository.publish_complete_event(
            published_event(source_item_ids=(first.id, second.id)), operation_id=1
        )
        repository.publish_complete_event(
            published_event(source_item_ids=(first.id,)), operation_id=1
        )
        memberships = db.scalars(select(EventItemRecord).order_by(EventItemRecord.id)).all()
        assert [(item.raw_item_id, item.removed_version_number) for item in memberships] == [
            (first.id, None),
            (second.id, 2),
        ]

        repository.publish_complete_event(published_event(), operation_id=1)
        repository.publish_complete_event(
            published_event(source_item_ids=(first.id,)), operation_id=1
        )
        active = db.scalars(
            select(EventItemRecord).where(EventItemRecord.removed_version_number.is_(None))
        ).all()
        assert len(active) == 1
        assert active[0].raw_item_id == first.id
        first_memberships = db.scalars(
            select(EventItemRecord).where(EventItemRecord.raw_item_id == first.id)
        ).all()
        assert len(first_memberships) == 2


def test_insert_rejects_unsupported_database_dialect() -> None:
    session_stub = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="mysql")))
    repository = EventRepository(session_stub)

    with pytest.raises(ValueError, match="Unsupported event repository dialect: mysql"):
        repository._insert(EventRecord)
