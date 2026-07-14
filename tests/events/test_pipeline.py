from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session, sessionmaker

from newsradar.db.models import (
    Base,
    EventItemRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    OperationRunRecord,
    RawItemProcessingRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.pipeline import ALGORITHM_VERSIONS, EventPipeline
from newsradar.events.relevance import (
    CONTENT_MAX_CHARS,
    ITEM_KIND_MAX_CHARS,
    PUBLISHER_MAX_CHARS,
    SOURCE_TOPIC_MAX_CHARS,
    SUMMARY_MAX_CHARS,
    TITLE_MAX_CHARS,
    evaluate_relevance,
)
from newsradar.events.repository import EventRepository
from newsradar.events.schema import ProcessingStage
from newsradar.settings import Settings
from newsradar.web.event_queries import EventQueryService


def test_pipeline_exposes_all_v2_rule_versions() -> None:
    assert ALGORITHM_VERSIONS == {
        "relevance": "relevance-v2",
        "entities": "entities-v2",
        "cluster": "cluster-v2",
        "score": "score-v2",
    }


def test_pipeline_scores_from_real_fields_using_operation_window_end() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    window_end = datetime(2025, 1, 4, 12, tzinfo=UTC)
    with Session(engine) as db:
        db.add(
            SourceDefinitionRecord(
                id="scored-source",
                name="Scored Source",
                status="active",
                nature="first_party",
                language="en",
                roles=["evidence"],
                topics=["ai"],
                authority_score=4,
                poll_interval_minutes=60,
                expected_fields=[],
                definition_hash="scored-source",
            )
        )
        db.add(
            RawItemRecord(
                source_id="scored-source",
                external_id="scored-item",
                canonical_url="https://example.test/scored-item",
                payload={},
                title="OpenAI launches Orion AI model",
                published_at=window_end - timedelta(hours=72),
                fetched_at=window_end,
                engagement={"score": 99, "invalid": -10},
            )
        )
        operation = OperationRunRecord(
            operation_type="event_pipeline",
            trigger="manual",
            status="queued",
            requested_scope={
                "window_hours": 72,
                "window_end": window_end.isoformat(),
            },
        )
        db.add(operation)
        db.commit()

        result = EventPipeline.production(db).run(
            window_hours=72,
            operation_id=operation.id,
            checkpoint=lambda _: None,
        )
        score = db.scalar(
            select(EventScoreRecord).where(
                EventScoreRecord.event_id == result.current_event_ids[0]
            )
        )
        event_record = db.get(EventRecord, result.current_event_ids[0])

    assert score is not None
    assert score.breakdown["ai_relevance"] == 100
    assert score.breakdown["source_coverage"] == 35
    assert score.breakdown["source_authority"] == 80
    assert score.breakdown["recency"] == 15
    assert score.breakdown["engagement_velocity"] > 0
    assert score.breakdown["novelty"] == 100
    assert score.breakdown["rule_version"] == "score-v2"
    assert event_record is not None
    assert event_record.visibility == "current"


def _source_record(*, topics: list[str] | None = None) -> SourceDefinitionRecord:
    return SourceDefinitionRecord(
        id="source",
        name="Source",
        status="active",
        nature="first_party",
        language="en",
        roles=["evidence"],
        topics=topics or ["ai"],
        authority_score=90,
        poll_interval_minutes=60,
        expected_fields=[],
        definition_hash="source",
    )


def test_selection_uses_bounded_projection_after_closing_read_session(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(_source_record(topics=["ai", *("x" * 500 for _ in range(30))]))
        db.add(
            RawItemRecord(
                source_id="source",
                external_id="bounded",
                canonical_url="https://example.test/bounded",
                payload={"must_not": "be selected"},
                raw_payload={"must_not": "be selected"},
                title="OpenAI launches multimodal model " + "x" * 1_000,
                summary="s" * 5_000,
                content="c" * 50_000,
                item_kind="kind" * 100,
                publisher_name="publisher" * 100,
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

    observed = []

    def observe_relevance(item):
        assert open_sessions == set()
        observed.append(item)
        return evaluate_relevance(item)

    selected_sql: list[str] = []

    def capture_sql(connection, cursor, statement, parameters, context, executemany):
        del connection, cursor, parameters, context, executemany
        if "FROM raw_items" in statement:
            selected_sql.append(statement.casefold())

    event.listen(engine, "before_cursor_execute", capture_sql)
    monkeypatch.setattr("newsradar.events.pipeline.evaluate_relevance", observe_relevance)
    factory = sessionmaker(bind=engine, class_=TrackingSession, expire_on_commit=False)
    try:
        result = EventPipeline(factory)._select_and_classify_items(72)
    finally:
        event.remove(engine, "before_cursor_execute", capture_sql)

    assert result.selected_count == 1
    assert len(observed) == 1
    item = observed[0]
    assert len(item.title) <= TITLE_MAX_CHARS
    assert len(item.summary) <= SUMMARY_MAX_CHARS
    assert len(item.content) <= CONTENT_MAX_CHARS
    assert len(item.item_kind or "") <= ITEM_KIND_MAX_CHARS
    assert len(item.publisher_name or "") <= PUBLISHER_MAX_CHARS
    assert len(item.source_topics) <= 20
    assert all(len(topic) <= SOURCE_TOPIC_MAX_CHARS for topic in item.source_topics)
    assert len(selected_sql) == 1
    assert "substr" in selected_sql[0]
    assert "raw_items.payload" not in selected_sql[0]
    assert "raw_items.raw_payload" not in selected_sql[0]


def test_selection_uses_frozen_72_hour_boundary_and_orders_by_id() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
    cutoff = now - timedelta(hours=72)
    with Session(engine) as db:
        db.add(_source_record())
        db.add_all(
            (
                RawItemRecord(
                    id=30,
                    source_id="source",
                    external_id="recent",
                    canonical_url="https://example.test/recent",
                    payload={},
                    title="OpenAI launches GPT model",
                    published_at=now,
                    fetched_at=now,
                ),
                RawItemRecord(
                    id=10,
                    source_id="source",
                    external_id="boundary",
                    canonical_url="https://example.test/boundary",
                    payload={},
                    title="Anthropic releases Claude SDK",
                    published_at=cutoff,
                    fetched_at=now,
                ),
                RawItemRecord(
                    id=20,
                    source_id="source",
                    external_id="too-old",
                    canonical_url="https://example.test/too-old",
                    payload={},
                    title="OpenAI publishes benchmark",
                    published_at=cutoff - timedelta(microseconds=1),
                    fetched_at=now,
                ),
            )
        )
        db.commit()

    selection = EventPipeline(
        sessionmaker(bind=engine, expire_on_commit=False)
    )._select_and_classify_items(72, now=now)

    assert [raw_item_id for raw_item_id, _ in selection.decisions] == [10, 30]


def test_entity_failure_keeps_committed_relevance_and_continues_clustering(
    monkeypatch, tmp_path
) -> None:
    database_path = (tmp_path / "entity-failure.db").as_posix()
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(_source_record())
        good = RawItemRecord(
            source_id="source",
            external_id="good",
            canonical_url="https://example.test/good",
            payload={},
            title="OpenAI launches GPT-5 model",
            published_at=datetime.now(UTC),
        )
        failed = RawItemRecord(
            source_id="source",
            external_id="failed",
            canonical_url="https://example.test/failed",
            payload={},
            title="Anthropic releases Claude SDK",
            published_at=datetime.now(UTC),
        )
        db.add_all((good, failed))
        db.commit()
        good_id = good.id
        failed_id = failed.id

    from newsradar.events.entities import extract_entities as real_extract_entities

    def fail_one_item(item):
        with Session(engine) as audit_session:
            relevance_ids = set(
                audit_session.scalars(
                    select(RawItemProcessingRecord.raw_item_id).where(
                        RawItemProcessingRecord.stage == ProcessingStage.RELEVANCE.value,
                        RawItemProcessingRecord.algorithm_version == "relevance-v2",
                    )
                )
            )
        assert relevance_ids == {good_id, failed_id}
        assert len(item.content) <= CONTENT_MAX_CHARS
        if item.raw_item_id == failed_id:
            raise RuntimeError("bad item")
        return real_extract_entities(item)

    monkeypatch.setattr("newsradar.events.pipeline.extract_entities", fail_one_item)
    with Session(engine) as db:
        result = EventPipeline.production(db).run(
            window_hours=72, operation_id=1, checkpoint=lambda _: None
        )
        entity_records = {
            record.raw_item_id: record
            for record in db.scalars(
                select(RawItemProcessingRecord).where(
                    RawItemProcessingRecord.stage == ProcessingStage.ENTITIES.value
                )
            )
        }
        clustered_ids = set(
            db.scalars(
                select(RawItemProcessingRecord.raw_item_id).where(
                    RawItemProcessingRecord.stage == ProcessingStage.CLUSTER.value
                )
            )
        )

    assert result.included_item_count == 2
    assert entity_records[failed_id].outcome == "failed"
    assert entity_records[failed_id].reason_codes == ["entity_extraction_failed"]
    assert clustered_ids == {good_id, failed_id}


def test_pipeline_records_included_and_excluded_items_using_published_or_fetched_time() -> (
    None
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
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
        included = RawItemRecord(
            source_id="source",
            external_id="included",
            canonical_url="https://example.test/included",
            payload={},
            title="OpenAI launches AI model",
            published_at=now,
            fetched_at=now,
        )
        excluded = RawItemRecord(
            source_id="source",
            external_id="excluded",
            canonical_url="https://example.test/excluded",
            payload={},
            title="Agent 64 game review",
            published_at=now,
            fetched_at=now,
        )
        missing_date = RawItemRecord(
            source_id="source",
            external_id="missing-date",
            canonical_url="https://example.test/missing-date",
            payload={},
            title="Generic company update",
            published_at=None,
            fetched_at=now,
        )
        stale_published = RawItemRecord(
            source_id="source",
            external_id="stale-published",
            canonical_url="https://example.test/stale-published",
            payload={},
            title="OpenAI launches another AI model",
            published_at=now - timedelta(hours=73),
            fetched_at=now,
        )
        db.add_all((included, excluded, missing_date, stale_published))
        db.commit()

        result = EventPipeline.production(db).run(
            window_hours=72,
            operation_id=1,
            checkpoint=lambda _: None,
        )

        assert result.selected_item_count == 3
        assert result.included_item_count == 1
        assert result.excluded_item_count == 2
        assert result.processed_item_count == 1
        decisions = {
            record.raw_item_id: record
            for record in db.scalars(
                select(RawItemProcessingRecord).where(
                    RawItemProcessingRecord.stage == ProcessingStage.RELEVANCE.value,
                    RawItemProcessingRecord.algorithm_version == "relevance-v2",
                )
            )
        }
        assert decisions[included.id].outcome == "included"
        assert decisions[excluded.id].outcome == "excluded"
        assert decisions[missing_date.id].outcome == "excluded"
        assert stale_published.id not in decisions
        assert set(
            db.scalars(
                select(RawItemProcessingRecord.raw_item_id).where(
                    RawItemProcessingRecord.stage == ProcessingStage.ENTITIES.value
                )
            )
        ) == {included.id}
        assert set(db.scalars(select(EventItemRecord.raw_item_id))) == {included.id}


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
