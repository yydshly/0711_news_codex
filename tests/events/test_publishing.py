from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from newsradar.ai.minimax import ModelUsage
from newsradar.db.models import (
    Base,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.publishing import EventPublisher
from newsradar.events.repository import EventRepository
from newsradar.events.schema import CandidateCluster, EventScoreInput, EventStatus


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def candidate(db_session: Session):
    db_session.add(
        SourceDefinitionRecord(
            id="source",
            name="Source",
            nature="professional_media",
            language="en",
            roles=["evidence"],
            topics=[],
            authority_score=90,
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
    db_session.add(item)
    db_session.flush()
    repository = EventRepository(db_session)
    record = repository.upsert_candidate(
        CandidateCluster(candidate_key="release", title="Release"), "cluster-v1"
    )
    repository.replace_candidate_items(record.id, (item.id,))
    db_session.commit()
    return record


def real_score_input() -> EventScoreInput:
    return EventScoreInput(
        ai_relevance=90,
        source_coverage=70,
        source_authority=80,
        recency=100,
        engagement_velocity=40,
        novelty=100,
        reasons=("engagement:log_normalized",),
    )


def test_reader_sees_only_complete_version(db_session: Session, candidate) -> None:
    publisher = EventPublisher(EventRepository(db_session))

    published = publisher.publish(
        candidate.id, operation_id=1, score_input=real_score_input()
    )

    current = EventRepository(db_session).get_current_event(published.event_id)
    assert current is not None
    assert current.version_number == 1
    score = db_session.scalar(
        select(EventScoreRecord).where(EventScoreRecord.event_id == published.event_id)
    )
    assert score is not None
    assert score.breakdown["rule_version"] == "score-v2"
    assert score.breakdown["ai_relevance"] == 90
    assert db_session.get(EventRecord, published.event_id).visibility == "current"


def test_publish_snapshot_materializes_tier_and_rank_in_version_and_event(
    db_session: Session,
) -> None:
    publisher = EventPublisher(EventRepository(db_session))

    published = publisher.publish_snapshot(
        CandidateCluster(candidate_key="ranked-release", title="OpenAI launches Orion"),
        operation_id=1,
        score_input=real_score_input(),
    )

    event = db_session.get(EventRecord, published.event_id)
    version = db_session.scalar(
        select(EventVersionRecord).where(EventVersionRecord.event_id == published.event_id)
    )
    assert event is not None
    assert version is not None
    assert published.display_tier.value == event.display_tier == "signal"
    assert published.rank_score == event.rank_score
    assert version.payload["publication"]["tier"] == "signal"


def test_publish_snapshot_persists_explainable_heat_and_trend(db_session: Session) -> None:
    publisher = EventPublisher(EventRepository(db_session))

    published = publisher.publish_snapshot(
        CandidateCluster(candidate_key="heat-release", title="OpenAI launches Orion"),
        operation_id=1,
        score_input=real_score_input(),
    )

    version = db_session.scalar(
        select(EventVersionRecord).where(EventVersionRecord.event_id == published.event_id)
    )
    assert version.payload["heat_breakdown"]["heat"] == published.score.heat
    assert version.payload["heat_breakdown"]["engagement_velocity"] == 40
    assert version.payload["trend"]["direction"] == "rising"
    assert version.payload["trend"]["reason"] == "trend:first_snapshot"


def test_publish_snapshot_uses_logical_snapshot_time_for_delayed_history(
    db_session: Session,
) -> None:
    """A retry may write an old immutable snapshot after its logical window closes."""
    publisher = EventPublisher(EventRepository(db_session))
    first_snapshot_at = datetime(2026, 7, 8, tzinfo=UTC)
    second_snapshot_at = first_snapshot_at + timedelta(days=1)
    first = publisher.publish_snapshot(
        CandidateCluster(candidate_key="delayed-history", title="First score"),
        operation_id=1,
        score_input=real_score_input(),
        snapshot_at=first_snapshot_at,
    )
    first_score = db_session.scalar(
        select(EventScoreRecord).where(EventScoreRecord.event_id == first.event_id)
    )
    assert first_score is not None
    first_score.created_at = second_snapshot_at + timedelta(minutes=5)
    db_session.commit()

    second = publisher.publish_snapshot(
        CandidateCluster(candidate_key="delayed-history", title="Second score"),
        operation_id=2,
        score_input=real_score_input().model_copy(update={"ai_relevance": 100}),
        snapshot_at=second_snapshot_at,
    )

    assert second.trend["reason"] == "trend:24h_persisted_snapshot"
    assert second.trend["baseline_heat"] == round(first.score.heat)


def test_publish_snapshot_passes_safe_model_summary_into_same_version(db_session: Session) -> None:
    publisher = EventPublisher(EventRepository(db_session))
    usage = ModelUsage(
        purpose="event_enrichment",
        model="MiniMax-M2.7-highspeed",
        input_tokens=10,
        output_tokens=5,
        latency_ms=21,
        outcome="fallback",
        error="timeout",
    )

    published = publisher.publish_snapshot(
        CandidateCluster(candidate_key="safe-model-run", title="Safe model run"),
        operation_id=1,
        score_input=real_score_input(),
        model_usages=(usage,),
    )

    version = db_session.scalar(
        select(EventVersionRecord).where(EventVersionRecord.event_id == published.event_id)
    )
    assert version.payload["model_runs"] == [
        {
            "model": "MiniMax-M2.7-highspeed",
            "purpose": "event_enrichment",
            "outcome": "fallback",
            "latency_ms": 21,
        }
    ]


def test_publisher_rejects_missing_score_input(db_session: Session, candidate) -> None:
    publisher = EventPublisher(EventRepository(db_session))

    with pytest.raises(TypeError):
        publisher.publish(candidate.id, operation_id=1)


def test_publisher_reconstructs_official_evidence_for_persisted_candidate(
    db_session: Session
) -> None:
    candidate = persisted_candidate(
        db_session,
        (("official", "first_party", "https://official.test/release"),),
    )

    published = EventPublisher(EventRepository(db_session)).publish(
        candidate.id, operation_id=1, score_input=real_score_input()
    )

    assert published.status is EventStatus.CONFIRMED
    assert published.score is not None
    assert published.score.credibility == 90


def test_publisher_confirms_two_independent_professional_roots(
    db_session: Session,
) -> None:
    candidate = persisted_candidate(
        db_session,
        (
            ("news-a", "professional_media", "https://news-a.test/release"),
            ("news-b", "professional_media", "https://news-b.test/release"),
        ),
    )

    published = EventPublisher(EventRepository(db_session)).publish(
        candidate.id, operation_id=1, score_input=real_score_input()
    )

    assert published.status is EventStatus.CONFIRMED
    assert published.score is not None
    assert published.score.credibility == 80


def test_publisher_persists_evidence_limitations_in_score_reasons(db_session: Session) -> None:
    candidate = persisted_candidate(
        db_session,
        (("research", "research", "https://arxiv.org/abs/1234.5678"),),
    )

    published = EventPublisher(EventRepository(db_session)).publish(
        candidate.id, operation_id=1, score_input=real_score_input()
    )

    score = db_session.scalar(
        select(EventScoreRecord).where(EventScoreRecord.event_id == published.event_id)
    )
    assert score is not None
    assert "evidence_limitation:not_peer_reviewed" in score.breakdown["reasons"]


def test_publisher_marks_persisted_conflicting_candidate_as_disputed(db_session: Session) -> None:
    candidate = persisted_candidate(
        db_session,
        (("official", "first_party", "https://official.test/release"),),
        reasons=("conflicting_action",),
    )

    published = EventPublisher(EventRepository(db_session)).publish(
        candidate.id, operation_id=1, score_input=real_score_input()
    )

    assert published.status is EventStatus.DISPUTED


def test_repository_has_no_incomplete_public_version_publish_path() -> None:
    assert not hasattr(EventRepository, "publish_version")


def test_failure_before_version_switch_preserves_previous_readable_version(
    db_session: Session, candidate, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = EventRepository(db_session)
    publisher = EventPublisher(repository)
    first = publisher.publish(
        candidate.id, operation_id=1, score_input=real_score_input()
    )
    db_session.commit()

    def fail_before_switch(*_args: object) -> None:
        raise RuntimeError("injected publish failure")

    monkeypatch.setattr(repository, "before_current_version_switch", fail_before_switch)

    with pytest.raises(RuntimeError, match="injected publish failure"):
        publisher.publish(candidate.id, operation_id=2, score_input=real_score_input())

    db_session.rollback()
    current = repository.get_current_event(first.event_id)
    assert current is not None
    assert current.version_number == 1
    assert db_session.scalars(select(EventVersionRecord)).all()[0].version_number == 1
    assert db_session.get(EventRecord, first.event_id).current_version_number == 1


def test_publisher_updates_legacy_event_to_current_visibility(
    db_session: Session, candidate
) -> None:
    publisher = EventPublisher(EventRepository(db_session))
    first = publisher.publish(
        candidate.id, operation_id=1, score_input=real_score_input()
    )
    record = db_session.get(EventRecord, first.event_id)
    record.visibility = "legacy"
    db_session.commit()

    publisher.publish(candidate.id, operation_id=2, score_input=real_score_input())

    assert db_session.get(EventRecord, first.event_id).visibility == "current"


def persisted_candidate(
    db_session: Session,
    sources: tuple[tuple[str, str, str], ...],
    reasons: tuple[str, ...] = (),
):
    raw_item_ids: list[int] = []
    for source_id, nature, canonical_url in sources:
        db_session.add(
            SourceDefinitionRecord(
                id=source_id,
                name=source_id,
                nature=nature,
                language="en",
                roles=["evidence"],
                topics=[],
                authority_score=90,
                poll_interval_minutes=60,
                expected_fields=[],
                definition_hash=f"hash-{source_id}",
            )
        )
        item = RawItemRecord(
            source_id=source_id,
            external_id="release",
            canonical_url=canonical_url,
            payload={},
        )
        db_session.add(item)
        db_session.flush()
        raw_item_ids.append(item.id)
    repository = EventRepository(db_session)
    record = repository.upsert_candidate(
        CandidateCluster(
            candidate_key=f"release:{sources[0][0]}",
            title="Release",
            reasons=reasons,
        ),
        "cluster-v1",
    )
    repository.replace_candidate_items(record.id, tuple(raw_item_ids))
    db_session.commit()
    return record
