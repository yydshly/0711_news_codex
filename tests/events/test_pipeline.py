from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    EventItemRecord,
    EventRecord,
    EventVersionRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.pipeline import EventPipeline
from newsradar.web.event_queries import EventQueryService


def test_pipeline_replay_does_not_duplicate_versions() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            SourceDefinitionRecord(
                id="source",
                name="Source",
                status="active",
                nature="first_party",
                language="en",
                roles=["evidence"],
                topics=["ai"],
                authority_score=90,
                poll_interval_minutes=60,
                expected_fields=[],
                definition_hash="source",
            )
        )
        db.add(
            RawItemRecord(
                source_id="source",
                external_id="1",
                canonical_url="https://example.test/1",
                payload={},
                title="OpenAI launches model",
                published_at=datetime.now(UTC),
            )
        )
        db.commit()

        pipeline = EventPipeline.production(db)
        first = pipeline.run(window_hours=24, operation_id=1, checkpoint=lambda _: None)
        second = pipeline.run(window_hours=24, operation_id=2, checkpoint=lambda _: None)

        assert first.current_event_ids
        assert second.created_event_versions == 0
        assert second.current_event_ids == first.current_event_ids
        assert db.query(EventVersionRecord).count() == 1


def test_pipeline_persists_audited_evidence_for_web_detail() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            SourceDefinitionRecord(
                id="official-source",
                name="Official",
                status="active",
                nature="first_party",
                language="en",
                roles=["evidence"],
                topics=["ai"],
                authority_score=90,
                poll_interval_minutes=60,
                expected_fields=[],
                definition_hash="official",
            )
        )
        db.add(
            RawItemRecord(
                source_id="official-source",
                external_id="official-1",
                canonical_url="https://example.test/official-1",
                payload={},
                title="OpenAI launches model",
                published_at=datetime.now(UTC),
            )
        )
        db.commit()
        event_id = (
            EventPipeline.production(db)
            .run(window_hours=24, operation_id=1, checkpoint=lambda _: None)
            .current_event_ids[0]
        )

        detail = EventQueryService(db).get_event(event_id)

    assert detail is not None
    assert detail.evidence[0].role == "official"
    assert detail.evidence[0].root_evidence_key == "https://example.test/official-1"
    assert detail.evidence[0].independent is True
    assert detail.evidence[0].limitations == ()


def test_pipeline_keeps_event_identity_and_source_publication_time_when_new_source_arrives() -> (
    None
):
    """A real event is keyed by its facts, not the transient set of member ids."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    published_at = datetime(2026, 7, 12, 9, 30, tzinfo=UTC)
    with Session(engine) as db:
        for source_id in ("official", "media"):
            db.add(
                SourceDefinitionRecord(
                    id=source_id,
                    name=source_id,
                    status="active",
                    nature="first_party" if source_id == "official" else "professional_media",
                    language="en",
                    roles=["evidence"],
                    topics=["ai"],
                    authority_score=90,
                    poll_interval_minutes=60,
                    expected_fields=[],
                    definition_hash=source_id,
                )
            )
        db.add(
            RawItemRecord(
                source_id="official",
                external_id="a",
                canonical_url="https://official.test/a",
                payload={},
                title="OpenAI launches Orion model",
                published_at=published_at,
            )
        )
        db.commit()
        first = EventPipeline.production(db).run(
            window_hours=24 * 365, operation_id=1, checkpoint=lambda _: None
        )
        event = db.get(EventRecord, first.current_event_ids[0])
        assert event is not None
        assert event.occurred_at is not None
        assert event.occurred_at.replace(tzinfo=UTC) == published_at
        canonical_key = event.canonical_key
        db.add(
            RawItemRecord(
                source_id="media",
                external_id="b",
                canonical_url="https://media.test/b",
                payload={},
                title="OpenAI launches Orion model",
                published_at=published_at,
            )
        )
        db.commit()
        second = EventPipeline.production(db).run(
            window_hours=24 * 365, operation_id=2, checkpoint=lambda _: None
        )
        db.expire_all()
        assert second.current_event_ids == first.current_event_ids
        event = db.get(EventRecord, first.current_event_ids[0])
        assert event is not None
        assert event.canonical_key == canonical_key
        assert event.current_version_number == 2
        assert set(
            db.scalars(
                EventItemRecord.__table__.select()
                .with_only_columns(EventItemRecord.raw_item_id)
                .where(
                    EventItemRecord.event_id == event.id,
                    EventItemRecord.removed_version_number.is_(None),
                )
            )
        ) == {1, 2}
