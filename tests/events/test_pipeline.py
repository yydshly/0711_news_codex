from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from newsradar.db.models import (
    Base,
    EventItemRecord,
    EventRecord,
    EventVersionRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.pipeline import EventPipeline
from newsradar.events.repository import EventRepository
from newsradar.settings import Settings
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
                title_fingerprint="openai-launches-orion-model",
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
                title_fingerprint="openai-launches-orion-model",
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


def test_minimax_invocation_has_no_open_session_or_event_lease_before_publication(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            SourceDefinitionRecord(
                id="official",
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
                source_id="official",
                external_id="first",
                canonical_url="https://official.test/first",
                payload={},
                title="OpenAI launches Orion model",
                title_fingerprint="openai-launches-orion-model",
                published_at=datetime.now(UTC),
            )
        )
        db.commit()

    open_sessions: set[Session] = set()

    class TrackingSession(Session):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            open_sessions.add(self)

        def close(self) -> None:
            try:
                super().close()
            finally:
                open_sessions.discard(self)

    factory = sessionmaker(bind=engine, class_=TrackingSession, expire_on_commit=False)
    settings = {"value": Settings(minimax_api_key=None)}
    monkeypatch.setattr("newsradar.events.pipeline.get_settings", lambda: settings["value"])
    pipeline = EventPipeline(factory)
    first = pipeline.run(window_hours=24, operation_id=1, checkpoint=lambda _: None)
    event_id = first.current_event_ids[0]

    with Session(engine) as db:
        db.add(
            RawItemRecord(
                source_id="official",
                external_id="second",
                canonical_url="https://official.test/second",
                payload={},
                title="OpenAI launches Orion model",
                title_fingerprint="openai-launches-orion-model",
                published_at=datetime.now(UTC),
            )
        )
        db.commit()

    order: list[str] = []

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

    async def observe_adapter(self, candidate, fallback):
        del self, candidate
        assert open_sessions == set()
        with engine.connect() as connection:
            lease_operation_id = connection.scalar(
                text("select lease_operation_id from events where id = :event_id"),
                {"event_id": event_id},
            )
        assert lease_operation_id is None
        order.append("adapter")
        return fallback

    original_claim = EventRepository.claim_event

    def observe_claim(self, claimed_event_id, operation_id, lease_until):
        assert order == ["adapter"]
        order.append("publication_lease")
        return original_claim(self, claimed_event_id, operation_id, lease_until)

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        "newsradar.events.pipeline.EventMiniMaxAdapter.enrich_event", observe_adapter
    )
    monkeypatch.setattr(EventRepository, "claim_event", observe_claim)
    settings["value"] = Settings(minimax_api_key="secret")

    pipeline.run(window_hours=24, operation_id=2, checkpoint=lambda _: None)

    assert order == ["adapter", "publication_lease"]
    assert open_sessions == set()
    with Session(engine) as db:
        event = db.get(EventRecord, event_id)
        assert event is not None
        assert event.lease_operation_id is None


def test_pipeline_counts_independent_evidence_items_suppressed_by_duplicate_root() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for source_id in ("official-a", "official-b"):
            db.add(
                SourceDefinitionRecord(
                    id=source_id,
                    name=source_id,
                    status="active",
                    nature="first_party",
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
                    source_id=source_id,
                    external_id="shared-release",
                    canonical_url="https://acme.test/releases/alpha",
                    payload={},
                    title="Acme launches Alpha model",
                    published_at=datetime.now(UTC),
                )
            )
        db.commit()

    with Session(engine) as db:
        result = EventPipeline.production(db).run(
            window_hours=24, operation_id=3, checkpoint=lambda _: None
        )

    assert result.duplicate_root_suppressed_count == 1
