from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

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
from newsradar.events.schema import CandidateCluster


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


def test_reader_sees_only_complete_version(db_session: Session, candidate) -> None:
    publisher = EventPublisher(EventRepository(db_session))

    published = publisher.publish(candidate.id, operation_id=1)

    current = EventRepository(db_session).get_current_event(published.event_id)
    assert current is not None
    assert current.version_number == 1
    score = db_session.scalar(
        select(EventScoreRecord).where(EventScoreRecord.event_id == published.event_id)
    )
    assert score is not None


def test_failure_before_version_switch_preserves_previous_readable_version(
    db_session: Session, candidate, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = EventRepository(db_session)
    publisher = EventPublisher(repository)
    first = publisher.publish(candidate.id, operation_id=1)
    db_session.commit()

    def fail_before_switch(*_args: object) -> None:
        raise RuntimeError("injected publish failure")

    monkeypatch.setattr(repository, "before_current_version_switch", fail_before_switch)

    with pytest.raises(RuntimeError, match="injected publish failure"):
        publisher.publish(candidate.id, operation_id=2)

    db_session.rollback()
    current = repository.get_current_event(first.event_id)
    assert current is not None
    assert current.version_number == 1
    assert db_session.scalars(select(EventVersionRecord)).all()[0].version_number == 1
    assert db_session.get(EventRecord, first.event_id).current_version_number == 1
