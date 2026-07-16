from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    EventCandidateRecord,
    EventItemRecord,
    EventMergeCandidateRecord,
    EventRecord,
    EventVersionRecord,
    OperationRunRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.event_merges.repository import EventMergeCandidateRepository
from newsradar.event_merges.service import EventMergeService

NOW = datetime(2026, 7, 16, 4, tzinfo=UTC)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
    engine.dispose()


def _source(source_id: str) -> SourceDefinitionRecord:
    return SourceDefinitionRecord(
        id=source_id,
        name=source_id,
        provider_id="independent",
        nature="media",
        language="en",
        roles=["evidence"],
        topics=["ai"],
        authority_score=80,
        poll_interval_minutes=60,
        expected_fields=["title"],
        definition_hash=(source_id[-1] * 64)[:64],
    )


def _seed_event(
    session: Session,
    event_id: int,
    raw_item_id: int,
    *,
    url: str,
    title: str = "OpenAI launches Orion model",
) -> None:
    source_id = f"source-{event_id}"
    session.add(_source(source_id))
    session.add(
        RawItemRecord(
            id=raw_item_id,
            source_id=source_id,
            external_id=f"item-{raw_item_id}",
            canonical_url=f"https://aggregator.example/{raw_item_id}",
            original_url=url,
            payload={},
            title=title,
            summary=title,
            published_at=NOW,
        )
    )
    session.add(
        EventRecord(
            id=event_id,
            canonical_key=f"event-{event_id}",
            visibility="current",
            status="confirmed",
            occurred_at=NOW,
            current_version_number=1,
        )
    )
    session.add_all(
        [
            EventVersionRecord(event_id=event_id, version_number=1, payload={}),
            EventItemRecord(
                event_id=event_id,
                raw_item_id=raw_item_id,
                added_version_number=1,
            ),
            EventCandidateRecord(
                candidate_key=f"event-{event_id}",
                algorithm_version="cluster-v3",
                title=title,
                state="active",
                metadata_json={},
            ),
        ]
    )


def _seed_scan_operation(session: Session, operation_id: int = 50) -> None:
    session.add(
        OperationRunRecord(
            id=operation_id,
            operation_type="event_merge_scan",
            trigger="test",
            status="running",
            requested_scope={},
            result_summary={},
        )
    )


def _rows(session: Session, model) -> list[tuple]:
    columns = tuple(model.__table__.columns)
    return list(session.execute(select(*columns).order_by(columns[0])).all())


def test_scan_writes_candidates_without_changing_event_or_source_state(session: Session) -> None:
    shared = "https://www.reuters.com/technology/orion-1?utm_source=feed"
    _seed_event(session, 1, 11, url=shared)
    _seed_event(session, 2, 22, url=shared)
    _seed_event(
        session,
        3,
        33,
        url="https://example.net/unrelated",
        title="Microsoft acquires Atlas project",
    )
    _seed_scan_operation(session)
    session.commit()
    protected = (
        EventRecord,
        EventVersionRecord,
        EventItemRecord,
        RawItemRecord,
        SourceDefinitionRecord,
    )
    before = {model: _rows(session, model) for model in protected}
    checkpoints: list[str] = []

    result = EventMergeService(session).scan(50, checkpoints.append)

    assert result.candidate_type_counts == {"deterministic_merge": 1}
    assert result.current_event_count == 3
    assert result.single_member_event_count == 3
    assert session.query(EventMergeCandidateRecord).count() == 1
    assert {model: _rows(session, model) for model in protected} == before
    assert checkpoints


def test_scan_isolates_malformed_event_and_continues(session: Session) -> None:
    shared = "https://www.reuters.com/technology/orion-1"
    _seed_event(session, 1, 11, url=shared)
    _seed_event(session, 2, 22, url=shared)
    session.add(
        EventRecord(
            id=3,
            canonical_key="malformed",
            visibility="current",
            status="confirmed",
            current_version_number=1,
        )
    )
    _seed_scan_operation(session)
    session.commit()

    result = EventMergeService(session).scan(50, lambda _: None)

    assert result.candidate_type_counts == {"deterministic_merge": 1}
    assert result.failure_reasons == {"fact_load_failed": 1}


def test_scan_does_not_compare_unindexed_unrelated_events(session: Session, monkeypatch) -> None:
    for event_id in range(1, 7):
        _seed_event(
            session,
            event_id,
            event_id * 10,
            url=f"https://example.com/story/{event_id}",
            title=f"Unique headline {event_id}",
        )
    _seed_scan_operation(session)
    session.commit()
    compared: list[tuple[int, int]] = []

    def record_pair(left, right, latest_snapshot_event_ids):
        compared.append((left.event_id, right.event_id))
        return None

    monkeypatch.setattr("newsradar.event_merges.service.classify_pair", record_pair)

    EventMergeService(session).scan(50, lambda _: None)

    assert compared == []


def test_scan_expires_pending_candidate_when_referenced_version_is_stale(
    session: Session,
) -> None:
    shared = "https://www.reuters.com/technology/orion-1"
    _seed_event(session, 1, 11, url=shared)
    _seed_event(session, 2, 22, url=shared)
    _seed_scan_operation(session, 50)
    session.commit()
    EventMergeService(session).scan(50, lambda _: None)
    stale = session.scalar(select(EventMergeCandidateRecord))
    assert stale is not None

    session.get(OperationRunRecord, 50).status = "succeeded"
    session.add(EventVersionRecord(event_id=1, version_number=2, payload={}))
    session.get(EventRecord, 1).current_version_number = 2
    _seed_scan_operation(session, 51)
    session.commit()

    result = EventMergeService(session).scan(51, lambda _: None)

    session.refresh(stale)
    assert stale.status == "expired"
    assert "referenced_version_no_longer_current" in stale.reason_codes
    assert result.status_counts == {"expired": 1, "pending": 1}


def test_scan_isolates_one_candidate_integrity_failure(
    session: Session, monkeypatch
) -> None:
    shared = "https://www.reuters.com/technology/orion-1"
    for event_id in (1, 2, 3):
        _seed_event(session, event_id, event_id * 10, url=shared)
    _seed_scan_operation(session)
    session.commit()
    original = EventMergeCandidateRepository.upsert_candidate
    attempts = 0

    def fail_first(self, draft, generated_operation_id):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise IntegrityError("candidate", {}, Exception("bounded failure"))
        return original(self, draft, generated_operation_id)

    monkeypatch.setattr(
        EventMergeCandidateRepository, "upsert_candidate", fail_first
    )

    result = EventMergeService(session).scan(50, lambda _: None)

    assert attempts == 3
    assert session.query(EventMergeCandidateRecord).count() == 2
    assert result.failure_reasons == {"candidate_integrity_failed": 1}
