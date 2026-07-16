from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    EventRecord,
    OperationRunRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.pipeline import EventPipeline
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS
from newsradar.settings import Settings

NOW = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _disable_external_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "newsradar.events.pipeline.get_settings",
        lambda: Settings(minimax_api_key=None),
    )


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _add_source_and_item(
    session: Session,
    *,
    source_id: str,
    nature: str,
    url: str,
    external_id: str,
    title: str = "OpenAI launches Orion reasoning model",
    original_url: str | None = None,
) -> None:
    if session.get(SourceDefinitionRecord, source_id) is None:
        session.add(
            SourceDefinitionRecord(
                id=source_id,
                name=source_id,
                provider_id=source_id,
                status="active",
                nature=nature,
                language="en",
                roles=["evidence"] if nature != "aggregator" else ["discovery"],
                topics=["ai", "foundation_models"],
                authority_score=90,
                poll_interval_minutes=60,
                expected_fields=[],
                definition_hash=(source_id * 64)[:64],
            )
        )
    session.add(
        RawItemRecord(
            source_id=source_id,
            external_id=external_id,
            canonical_url=url,
            original_url=original_url or url,
            payload={},
            title=title,
            summary="OpenAI released the Orion reasoning model for developers.",
            publisher_name=source_id,
            published_at=NOW,
            fetched_at=NOW,
        )
    )
    session.commit()


def _run(session: Session, operation_id: int):
    session.add(
        OperationRunRecord(
            id=operation_id,
            operation_type="event_pipeline",
            trigger="test",
            status="running",
            requested_scope={
                "window_hours": 24,
                "window_end": NOW.isoformat(),
                "algorithm_versions": dict(EVENT_ALGORITHM_VERSIONS),
            },
            result_summary={},
        )
    )
    session.commit()
    return EventPipeline.production(session).run(
        window_hours=24,
        operation_id=operation_id,
        checkpoint=lambda _: None,
    )


def test_official_item_publishes_confirmed_event() -> None:
    with Session(_engine()) as session:
        _add_source_and_item(
            session,
            source_id="official",
            nature="first_party",
            url="https://official.test/orion",
            external_id="official-orion",
        )
        result = _run(session, 1)

    assert result.confirmed_event_count == 1
    assert result.events_with_official_root == 1
    assert result.model_fallback_count == 1


def test_two_independent_professional_sources_confirm_one_event() -> None:
    with Session(_engine()) as session:
        _add_source_and_item(
            session,
            source_id="media-a",
            nature="professional_media",
            url="https://a.test/orion",
            external_id="a-orion",
        )
        _add_source_and_item(
            session,
            source_id="media-b",
            nature="professional_media",
            url="https://b.test/orion",
            external_id="b-orion",
        )
        result = _run(session, 1)

    assert result.current_event_ids and len(result.current_event_ids) == 1
    assert result.confirmed_event_count == 1
    assert result.events_with_two_professional_roots == 1


def test_aggregator_and_one_media_remain_emerging() -> None:
    with Session(_engine()) as session:
        _add_source_and_item(
            session,
            source_id="google-news",
            nature="aggregator",
            url="https://news.test/orion",
            external_id="google-orion",
        )
        _add_source_and_item(
            session,
            source_id="media-a",
            nature="professional_media",
            url="https://a.test/orion",
            external_id="a-orion",
        )
        result = _run(session, 1)

    assert result.current_event_ids and len(result.current_event_ids) == 1
    assert result.confirmed_event_count == 0
    assert result.events_with_one_professional_root == 1


def test_later_evidence_upgrades_same_event_without_duplicate() -> None:
    with Session(_engine()) as session:
        _add_source_and_item(
            session,
            source_id="media-a",
            nature="professional_media",
            url="https://a.test/orion",
            external_id="a-orion",
        )
        first = _run(session, 1)
        first_event_id = first.current_event_ids[0]
        _add_source_and_item(
            session,
            source_id="media-b",
            nature="professional_media",
            url="https://b.test/orion",
            external_id="b-orion",
        )
        second = _run(session, 2)
        event = session.get(EventRecord, first_event_id)

        assert second.current_event_ids == (first_event_id,)
        assert second.confirmed_event_count == 1
        assert event is not None and event.current_version_number == 2
        assert session.scalar(select(func.count()).select_from(EventRecord)) == 1


def test_media_copy_of_official_upstream_does_not_add_independent_root() -> None:
    official_url = "https://official.test/orion"
    with Session(_engine()) as session:
        _add_source_and_item(
            session,
            source_id="official",
            nature="first_party",
            url=official_url,
            external_id="official-orion",
        )
        _add_source_and_item(
            session,
            source_id="media-a",
            nature="professional_media",
            url="https://a.test/orion-copy",
            original_url=official_url,
            external_id="a-copy",
        )
        result = _run(session, 1)

    assert len(result.current_event_ids) == 1
    assert result.confirmed_event_count == 1
    assert result.events_with_official_root == 1
    assert result.events_with_one_professional_root == 0


def test_repeating_same_evidence_is_idempotent() -> None:
    with Session(_engine()) as session:
        _add_source_and_item(
            session,
            source_id="official",
            nature="first_party",
            url="https://official.test/orion",
            external_id="official-orion",
        )
        first = _run(session, 1)
        second = _run(session, 2)
        event = session.get(EventRecord, first.current_event_ids[0])

        assert second.current_event_ids == first.current_event_ids
        assert second.created_event_versions == 0
        assert event is not None and event.current_version_number == 1
        assert session.scalar(select(func.count()).select_from(EventRecord)) == 1
