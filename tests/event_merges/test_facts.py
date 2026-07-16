from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    EventCandidateRecord,
    EventItemRecord,
    EventRecord,
    EventVersionRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.event_merges.facts import load_event_facts


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
    engine.dispose()


def _seed_event(
    session: Session,
    *,
    canonical_url: str,
    original_url: str | None,
) -> int:
    source = SourceDefinitionRecord(
        id="source-1",
        name="Source One",
        provider_id="independent",
        nature="media",
        language="en",
        roles=["evidence"],
        topics=["ai"],
        authority_score=80,
        poll_interval_minutes=60,
        expected_fields=["title"],
        definition_hash="a" * 64,
    )
    raw = RawItemRecord(
        id=10,
        source_id=source.id,
        external_id="item-10",
        canonical_url=canonical_url,
        original_url=original_url,
        payload={},
        title="OpenAI launches Orion model with 128 parameters",
        summary="The Orion model was released today.",
        content="",
        publisher_name="Reuters",
        published_at=datetime(2026, 7, 16, 4, tzinfo=UTC),
    )
    event = EventRecord(
        id=1,
        canonical_key="event-1",
        visibility="current",
        status="confirmed",
        occurred_at=raw.published_at,
        current_version_number=1,
    )
    session.add_all(
        [
            source,
            raw,
            event,
            EventVersionRecord(
                event_id=event.id,
                version_number=1,
                payload={"evidence": [{"root_evidence_key": "publisher:reuters"}]},
            ),
            EventItemRecord(
                event_id=event.id,
                raw_item_id=raw.id,
                added_version_number=1,
            ),
            EventCandidateRecord(
                candidate_key=event.canonical_key,
                algorithm_version="cluster-v3",
                title=raw.title or "",
                state="active",
                metadata_json={},
            ),
        ]
    )
    session.commit()
    return event.id


def test_event_facts_exclude_google_news_intermediary_from_strong_identity(session) -> None:
    event_id = _seed_event(
        session,
        canonical_url="https://news.google.com/rss/articles/abc?token=secret",
        original_url="https://news.google.com/rss/articles/abc?token=secret",
    )

    facts = load_event_facts(session, event_id)

    assert facts.safe_url_identities == ("news.google.com/rss/articles/abc",)
    assert facts.strong_identities == ()
    assert facts.actions == ("launch",)
    assert "secret" not in repr(facts)


def test_event_facts_keep_real_original_media_identity(session) -> None:
    event_id = _seed_event(
        session,
        canonical_url="https://example.com/story?id=secret",
        original_url="https://www.reuters.com/technology/story-123?utm_source=x",
    )

    facts = load_event_facts(session, event_id)

    assert "www.reuters.com/technology/story-123" in facts.strong_identities
    assert "secret" not in repr(facts)


def test_event_facts_sort_and_deduplicate_active_membership(session) -> None:
    event_id = _seed_event(
        session,
        canonical_url="https://example.com/story",
        original_url="https://www.reuters.com/story",
    )
    session.add(
        EventItemRecord(
            event_id=event_id,
            raw_item_id=10,
            added_version_number=0,
        )
    )
    session.commit()

    facts = load_event_facts(session, event_id)

    assert facts.raw_item_ids == (10,)
