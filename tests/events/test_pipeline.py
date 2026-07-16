import asyncio
from datetime import UTC, datetime, timedelta
from threading import Lock

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session, sessionmaker

from newsradar.ai.minimax import ModelUsage
from newsradar.db.models import (
    Base,
    EventCandidateRecord,
    EventItemRecord,
    EventModelRunRecord,
    EventPairDecisionRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    OperationRunRecord,
    RawItemProcessingRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.minimax import EventEnrichmentResult, EventModelRun
from newsradar.events.pipeline import (
    ALGORITHM_VERSIONS,
    EventPipeline,
    _bounded_engagement,
)
from newsradar.events.publishing import rule_enrichment
from newsradar.events.relevance import (
    CONTENT_MAX_CHARS,
    ITEM_KIND_MAX_CHARS,
    PUBLISHER_MAX_CHARS,
    SOURCE_TOPIC_MAX_CHARS,
    SUMMARY_MAX_CHARS,
    TITLE_MAX_CHARS,
    evaluate_relevance,
)
from newsradar.events.repository import EventPublicationConflict, EventRepository
from newsradar.events.schema import (
    CandidateCluster,
    ClusterItem,
    PairSemanticDecision,
    ProcessingStage,
)
from newsradar.settings import Settings
from newsradar.web.event_queries import EventQueryService


@pytest.fixture(autouse=True)
def _disable_live_minimax_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep pipeline unit tests isolated from a developer's real local API key."""
    monkeypatch.setattr(
        "newsradar.events.pipeline.get_settings",
        lambda: Settings(minimax_api_key=None),
    )


def _seed_operation(
    session: Session,
    operation_id: int,
    *,
    window_end: datetime | None = None,
) -> None:
    snapshot = window_end or datetime.now(UTC)
    session.add(
        OperationRunRecord(
            id=operation_id,
            operation_type="event_pipeline",
            trigger="manual",
            status="running",
            requested_scope={"window_end": snapshot.isoformat()},
            created_at=snapshot,
        )
    )


def test_pipeline_exposes_current_rule_versions() -> None:
    assert ALGORITHM_VERSIONS == {
        "relevance": "relevance-v2",
        "newsworthiness": "newsworthiness-v2",
        "entities": "entities-v2",
        "cluster": "cluster-v3",
        "score": "score-v2",
    }


def test_pipeline_batch_enrichment_is_bounded_to_two_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add(_source_record())
        for index, title in enumerate(
            (
                "OpenAI launches Alpha AI model",
                "Anthropic releases Beta AI model",
                "Google unveils Gamma AI model",
                "Meta debuts Delta AI model",
                "Mistral introduces Epsilon AI model",
            ),
            start=1,
        ):
            db.add(
                RawItemRecord(
                    source_id="source",
                    external_id=str(index),
                    canonical_url=f"https://example.test/{index}",
                    payload={},
                    title=title,
                    published_at=now,
                )
            )
        _seed_operation(db, 101, window_end=now)
        db.commit()

    lock = Lock()
    active = 0
    maximum_active = 0

    async def tracked_enrichment(candidate, fallback, settings, http):
        nonlocal active, maximum_active
        del fallback, settings, http
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.03)
        with lock:
            active -= 1
        return EventEnrichmentResult(
            enrichment=rule_enrichment(candidate).model_copy(
                update={"origin": "model"}
            ),
            model_runs=(
                EventModelRun(
                    stage="event_enrichment",
                    usage=ModelUsage(
                        purpose="event_enrichment",
                        model="fixture",
                        input_tokens=10,
                        output_tokens=2,
                        latency_ms=1,
                        outcome="success",
                    ),
                ),
            ),
        )

    monkeypatch.setattr(
        EventPipeline, "_enrich_candidate_async", staticmethod(tracked_enrichment)
    )
    monkeypatch.setattr(
        "newsradar.events.pipeline.get_settings",
        lambda: Settings(event_model_max_concurrency=5),
    )
    with Session(engine) as db:
        result = EventPipeline.production(db).run(
            window_hours=24,
            operation_id=101,
            checkpoint=lambda _: None,
        )

    assert result.candidate_count == 5
    assert maximum_active == 2
    assert result.model_success_count == 4
    assert result.model_fallback_count == 0
    assert result.model_input_tokens == 40
    assert result.model_output_tokens == 8


def test_pipeline_skips_model_for_low_rank_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add(
            SourceDefinitionRecord(
                id="community",
                name="Community",
                status="active",
                nature="community",
                language="en",
                roles=["discovery"],
                topics=["ai"],
                authority_score=10,
                poll_interval_minutes=60,
                expected_fields=[],
                definition_hash="community",
            )
        )
        db.add(
            RawItemRecord(
                source_id="community",
                external_id="low-rank",
                canonical_url="https://example.test/low-rank",
                payload={},
                title="OpenAI launches a community model",
                published_at=now,
            )
        )
        _seed_operation(db, 104, window_end=now)
        db.commit()

    async def unexpected_model_call(*args, **kwargs):
        del args, kwargs
        raise AssertionError("low-rank signal must not call MiniMax")

    monkeypatch.setattr(
        EventPipeline, "_enrich_candidate_async", staticmethod(unexpected_model_call)
    )
    with Session(engine) as db:
        result = EventPipeline.production(db).run(
            window_hours=24,
            operation_id=104,
            checkpoint=lambda _: None,
        )

    assert result.model_success_count == 0
    assert result.model_fallback_count == 0


def test_pipeline_records_all_required_stage_checkpoints() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add(_source_record())
        db.add(
            RawItemRecord(
                source_id="source",
                external_id="checkpoint",
                canonical_url="https://example.test/checkpoint",
                payload={},
                title="OpenAI launches checkpoint AI model",
                published_at=now,
            )
        )
        _seed_operation(db, 102, window_end=now)
        db.commit()

    checkpoints: list[str] = []
    with Session(engine) as db:
        EventPipeline.production(db).run(
            window_hours=24,
            operation_id=102,
            checkpoint=checkpoints.append,
        )

    assert {
        "after_event_selection",
        "after_event_relevance",
        "after_event_newsworthiness",
        "after_event_cluster",
        "before_event_enrichment",
        "after_event_enrichment",
        "after_event_publish",
    }.issubset(checkpoints)


def test_pipeline_excludes_relevant_item_without_a_discrete_news_action() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add(_source_record())
        db.add_all(
            (
                RawItemRecord(
                    source_id="source",
                    external_id="status-update",
                    canonical_url="https://example.test/status-update",
                    payload={},
                    title="OpenAI safety update",
                    published_at=now,
                ),
                RawItemRecord(
                    source_id="source",
                    external_id="product-release",
                    canonical_url="https://example.test/product-release",
                    payload={},
                    title="OpenAI launches an AI API",
                    published_at=now,
                ),
            )
        )
        _seed_operation(db, 103, window_end=now)
        db.commit()

    with Session(engine) as db:
        result = EventPipeline.production(db).run(
            window_hours=24,
            operation_id=103,
            checkpoint=lambda _: None,
        )

    assert result.selected_item_count == 2
    assert result.included_item_count == 1
    assert result.newsworthy_item_count == 1
    assert result.non_newsworthy_item_count == 1
    assert result.newsworthiness_reasons == {"no_event_action": 1}
    with Session(engine) as db:
        records = tuple(
            db.scalars(
                select(RawItemProcessingRecord).where(
                    RawItemProcessingRecord.stage == "newsworthiness"
                )
            )
        )

    assert {(record.raw_item_id, record.outcome) for record in records} == {
        (1, "excluded"),
        (2, "included"),
    }


def test_pipeline_records_direct_pair_decision_before_clustering() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    items = (
        ClusterItem(
            raw_item_id=1,
            title="OpenAI launches Orion model",
            canonical_url="https://official.example.test/orion",
            published_at=now,
        ),
        ClusterItem(
            raw_item_id=2,
            title="OpenAI launches Orion model",
            canonical_url="https://official.example.test/orion",
            published_at=now,
        ),
    )

    with Session(engine) as db:
        decisions = EventPipeline.production(db)._resolve_pair_decisions(items)

    assert decisions[(1, 2)].decision == "merge"
    with Session(engine) as db:
        record = db.scalar(select(EventPairDecisionRecord))

    assert record is not None
    assert record.final_decision == "merge"


def test_pipeline_reuses_audited_pair_decision_on_replay() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    items = (
        ClusterItem(
            raw_item_id=1,
            title="OpenAI launches Orion model",
            canonical_url="https://official.example.test/orion",
            published_at=now,
        ),
        ClusterItem(
            raw_item_id=2,
            title="OpenAI launches Orion model",
            canonical_url="https://official.example.test/orion",
            published_at=now,
        ),
    )

    with Session(engine) as db:
        pipeline = EventPipeline.production(db)
        first = pipeline._resolve_pair_decisions(items)
        second = pipeline._resolve_pair_decisions(items)

    assert first == second
    with Session(engine) as db:
        assert db.query(EventPairDecisionRecord).count() == 1


def test_pipeline_uses_model_only_for_anchored_boundary_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    items = (
        ClusterItem(
            raw_item_id=1,
            title="OpenAI launches Orion reasoning model",
            entities=("model:orion",),
            published_at=now,
        ),
        ClusterItem(
            raw_item_id=2,
            title="Orion reasoning model released by OpenAI",
            entities=("model:orion",),
            published_at=now,
        ),
    )
    calls: list[tuple[int, int]] = []

    async def compare(self, left, right):
        del self
        calls.append((left.raw_item_ids[0], right.raw_item_ids[0]))
        return PairSemanticDecision(
            decision="same_event",
            confidence=0.91,
            rationale="same launch",
            origin="model",
        )

    monkeypatch.setattr(
        "newsradar.events.pipeline.EventMiniMaxAdapter.compare_candidate_pair", compare
    )
    with Session(engine) as db:
        decisions = EventPipeline.production(db)._resolve_pair_decisions(items)

    assert calls == [(1, 2)]
    assert decisions[(1, 2)].decision == "merge"


def test_pipeline_counts_boundary_fallback_and_cached_uncertain_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    items = (
        ClusterItem(
            raw_item_id=1,
            title="OpenAI launches Orion reasoning model",
            entities=("model:orion",),
            published_at=now,
        ),
        ClusterItem(
            raw_item_id=2,
            title="Orion reasoning model released by OpenAI",
            entities=("model:orion",),
            published_at=now,
        ),
    )

    async def compare(self, left, right):
        del self, left, right
        return PairSemanticDecision(
            decision="uncertain",
            confidence=0,
            rationale="规则回退：语义配对不可用",
            origin="rule_fallback",
        )

    monkeypatch.setattr(
        "newsradar.events.pipeline.EventMiniMaxAdapter.compare_candidate_pair", compare
    )
    with Session(engine) as db:
        pipeline = EventPipeline.production(db)
        first = pipeline._resolve_pair_decisions(items)
        second = pipeline._resolve_pair_decisions(items)

    assert first[(1, 2)].decision == "separate"
    assert first[(1, 2)].model_same_event is None
    assert second == first
    assert pipeline._pair_metrics["ambiguous_checked"] == 2
    assert pipeline._pair_metrics["model_pair_fallback"] == 2
    assert pipeline._pair_metrics["cache_hit"] == 1


def test_pipeline_cached_explicit_different_event_is_not_counted_as_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    items = (
        ClusterItem(
            raw_item_id=1,
            title="OpenAI launches Orion reasoning model",
            entities=("model:orion",),
            published_at=now,
        ),
        ClusterItem(
            raw_item_id=2,
            title="Orion reasoning model released by OpenAI",
            entities=("model:orion",),
            published_at=now,
        ),
    )

    async def compare(self, left, right):
        del self, left, right
        return PairSemanticDecision(
            decision="different_event",
            confidence=0.92,
            rationale="different releases",
            origin="model",
        )

    monkeypatch.setattr(
        "newsradar.events.pipeline.EventMiniMaxAdapter.compare_candidate_pair", compare
    )
    with Session(engine) as db:
        pipeline = EventPipeline.production(db)
        pipeline._resolve_pair_decisions(items)
        pipeline._resolve_pair_decisions(items)

    assert pipeline._pair_metrics["ambiguous_checked"] == 2
    assert pipeline._pair_metrics["model_pair_fallback"] == 0


def test_pipeline_checkpoint_cancels_inflight_async_enrichment_promptly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled: list[str] = []
    candidates = tuple(
        CandidateCluster(
            candidate_key=f"cancel-{index}",
            title=f"Candidate {index}",
            items=(ClusterItem(raw_item_id=index + 1, title=f"Item {index}"),),
            raw_item_ids=(index + 1,),
        )
        for index in range(4)
    )

    async def hanging(candidate, fallback, settings, http):
        del fallback, settings, http
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(candidate.candidate_key)
            raise

    def checkpoint(candidate: CandidateCluster) -> None:
        if candidate.candidate_key == "cancel-1":
            raise RuntimeError("operation_cancelled")

    monkeypatch.setattr(
        EventPipeline, "_enrich_candidate_async", staticmethod(hanging)
    )
    with pytest.raises(RuntimeError, match="operation_cancelled"):
        EventPipeline._enrich_candidates(
            candidates, candidate_checkpoint=checkpoint
        )

    assert cancelled == ["cancel-0"]


def test_pipeline_enrichment_batch_receives_only_rule_included_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add(_source_record())
        db.add_all(
            (
                RawItemRecord(
                    source_id="source",
                    external_id="included-model",
                    canonical_url="https://example.test/included-model",
                    payload={},
                    title="OpenAI launches included AI model",
                    published_at=now,
                ),
                RawItemRecord(
                    source_id="source",
                    external_id="excluded-game",
                    canonical_url="https://example.test/excluded-game",
                    payload={},
                    title="Agent 64 game review",
                    published_at=now,
                ),
            )
        )
        _seed_operation(db, 103, window_end=now)
        db.commit()

    enriched_item_ids: list[tuple[int, ...]] = []

    async def observe(candidate, fallback, settings, http):
        del fallback, settings, http
        enriched_item_ids.append(candidate.raw_item_ids)
        return EventEnrichmentResult(enrichment=rule_enrichment(candidate))

    monkeypatch.setattr(
        EventPipeline, "_enrich_candidate_async", staticmethod(observe)
    )
    with Session(engine) as db:
        result = EventPipeline.production(db).run(
            window_hours=24,
            operation_id=103,
            checkpoint=lambda _: None,
        )

    assert result.included_item_count == 1
    assert result.excluded_item_count == 1
    assert enriched_item_ids == [(1,)]


def test_bounded_engagement_filters_whitelist_before_field_limit() -> None:
    values = {f"aaa_noise_{index:02d}": index for index in range(20)}
    values.update({"views": 500, "score": 20})

    assert _bounded_engagement(values, max_count=1) == {"score": 20}


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
        db.add(
            RawItemRecord(
                source_id="scored-source",
                external_id="future-item",
                canonical_url="https://example.test/future-item",
                payload={},
                title="OpenAI launches Future Orion AI model",
                published_at=window_end + timedelta(days=10),
                fetched_at=window_end + timedelta(days=10),
                engagement={"score": 10_000},
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
    assert result.selected_item_count == 1
    assert score.breakdown["ai_relevance"] == 100
    assert score.breakdown["source_coverage"] == 35
    assert score.breakdown["source_authority"] == 80
    assert score.breakdown["recency"] == 15
    assert score.breakdown["engagement_velocity"] > 0
    assert score.breakdown["novelty"] == 100
    assert score.breakdown["rule_version"] == "score-v2"
    assert event_record is not None
    assert event_record.visibility == "current"


def test_operation_window_end_accepts_naive_iso_as_utc() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        operation = OperationRunRecord(
            operation_type="event_pipeline",
            trigger="manual",
            status="queued",
            requested_scope={"window_end": "2025-01-04T12:00:00"},
        )
        db.add(operation)
        db.commit()

        result = EventPipeline.production(db)._operation_window_end(operation.id)

    assert result == datetime(2025, 1, 4, 12, tzinfo=UTC)


@pytest.mark.parametrize("scope", [{}, {"window_end": "not-a-date"}])
def test_operation_window_end_falls_back_to_stable_created_at_and_records_reason(
    scope: dict[str, object],
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    created_at = datetime(2025, 2, 3, 4, 5, tzinfo=UTC)
    with Session(engine) as db:
        operation = OperationRunRecord(
            operation_type="event_pipeline",
            trigger="manual",
            status="queued",
            requested_scope=scope,
            created_at=created_at,
        )
        db.add(operation)
        db.commit()
        checkpoints: list[str] = []

        result = EventPipeline.production(db)._operation_window_end(
            operation.id, checkpoint=checkpoints.append
        )

    assert result == created_at
    assert checkpoints == ["operation_window_end_fallback"]


def test_operation_window_end_rejects_missing_operation() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        pipeline = EventPipeline.production(db)

        with pytest.raises(LookupError, match="operation 99 does not exist"):
            pipeline._operation_window_end(99)


def test_pipeline_novelty_finds_same_core_identity_in_prior_30_day_current_event() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    first_now = datetime(2025, 3, 1, 12, tzinfo=UTC)
    second_now = first_now + timedelta(hours=72)
    with Session(engine) as db:
        for source_id, nature, authority in (
            ("official", "first_party", 5),
            ("media", "professional_media", 4),
        ):
            db.add(
                SourceDefinitionRecord(
                    id=source_id,
                    name=source_id,
                    status="active",
                    nature=nature,
                    language="en",
                    roles=["evidence"],
                    topics=["ai"],
                    authority_score=authority,
                    poll_interval_minutes=60,
                    expected_fields=[],
                    definition_hash=source_id,
                )
            )
        first_item = RawItemRecord(
            source_id="official",
            external_id="orion-first",
            canonical_url="https://official.test/orion",
            payload={},
            title="OpenAI launches Orion model",
            published_at=first_now,
            fetched_at=first_now,
        )
        first_operation = OperationRunRecord(
            operation_type="event_pipeline",
            trigger="manual",
            status="queued",
            requested_scope={"window_hours": 72, "window_end": first_now.isoformat()},
            created_at=first_now,
        )
        db.add_all((first_item, first_operation))
        db.commit()
        first_result = EventPipeline.production(db).run(
            window_hours=72,
            operation_id=first_operation.id,
            checkpoint=lambda _: None,
        )
        assert first_result.created_event_versions == 1

        second_item = RawItemRecord(
            source_id="media",
            external_id="orion-second",
            canonical_url="https://media.test/orion-followup",
            payload={},
            title="Orion model released by OpenAI",
            published_at=second_now,
            fetched_at=second_now,
        )
        second_operation = OperationRunRecord(
            operation_type="event_pipeline",
            trigger="manual",
            status="queued",
            requested_scope={"window_hours": 72, "window_end": second_now.isoformat()},
            created_at=second_now,
        )
        db.add_all((second_item, second_operation))
        db.commit()

        second_result = EventPipeline.production(db).run(
            window_hours=72,
            operation_id=second_operation.id,
            checkpoint=lambda _: None,
        )
        scores = tuple(
            db.scalars(select(EventScoreRecord).order_by(EventScoreRecord.event_id))
        )

    assert second_result.created_event_versions == 1
    assert len(scores) == 2
    assert scores[0].breakdown["novelty"] == 100
    assert scores[1].breakdown["novelty"] == 50


def test_pipeline_publishes_same_candidate_snapshot_used_for_score_when_members_are_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    window_end = datetime(2025, 4, 1, 12, tzinfo=UTC)
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
                authority_score=5,
                poll_interval_minutes=60,
                expected_fields=[],
                definition_hash="official",
            )
        )
        selected = RawItemRecord(
            source_id="official",
            external_id="selected",
            canonical_url="https://official.test/selected",
            payload={},
            title="OpenAI launches Orion model",
            published_at=window_end,
            fetched_at=window_end,
        )
        replacement = RawItemRecord(
            source_id="official",
            external_id="replacement",
            canonical_url="https://official.test/replacement",
            payload={},
            title="OpenAI launches Replacement model",
            published_at=window_end + timedelta(days=10),
            fetched_at=window_end + timedelta(days=10),
        )
        operation = OperationRunRecord(
            operation_type="event_pipeline",
            trigger="manual",
            status="queued",
            requested_scope={"window_hours": 72, "window_end": window_end.isoformat()},
            created_at=window_end,
        )
        db.add_all((selected, replacement, operation))
        db.commit()
        selected_id, replacement_id, operation_id = (
            selected.id,
            replacement.id,
            operation.id,
        )

    async def replace_members(candidate, fallback, settings, http):
        del fallback, settings, http
        with Session(engine) as other:
            record = other.scalar(
                select(EventCandidateRecord).where(
                    EventCandidateRecord.candidate_key == candidate.candidate_key
                )
            )
            assert record is not None
            EventRepository(other).replace_candidate_items(record.id, (replacement_id,))
            other.commit()
        return EventEnrichmentResult(enrichment=rule_enrichment(candidate))

    monkeypatch.setattr(
        EventPipeline, "_enrich_candidate_async", staticmethod(replace_members)
    )
    with Session(engine) as db:
        result = EventPipeline.production(db).run(
            window_hours=72,
            operation_id=operation_id,
            checkpoint=lambda _: None,
        )
        active_ids = set(
            db.scalars(
                select(EventItemRecord.raw_item_id).where(
                    EventItemRecord.event_id == result.current_event_ids[0],
                    EventItemRecord.removed_version_number.is_(None),
                )
            )
        )
        version = db.scalar(select(EventVersionRecord))

    assert active_ids == {selected_id}
    assert version is not None
    assert version.payload["source_item_ids"] == [selected_id]
    assert version.payload["evidence"][0]["root_evidence_key"] == (
        "https://official.test/selected"
    )


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
        _seed_operation(db, 1)
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
        _seed_operation(db, 1)
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
        _seed_operation(db, 1, window_end=now)
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
        snapshot = datetime.now(UTC)
        _seed_operation(db, 1, window_end=snapshot)
        _seed_operation(db, 2, window_end=snapshot)
        db.commit()

        pipeline = EventPipeline.production(db)
        first = pipeline.run(window_hours=24, operation_id=1, checkpoint=lambda _: None)
        second = pipeline.run(window_hours=24, operation_id=2, checkpoint=lambda _: None)

        assert first.current_event_ids
        assert second.created_event_versions == 0
        assert second.current_event_ids == first.current_event_ids
        assert db.query(EventVersionRecord).count() == 1


def test_same_snapshot_won_during_claim_creates_one_version_and_audits_loser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B's stale pre-read must converge on A's snapshot after B acquires the lease."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add(_source_record())
        db.add(
            RawItemRecord(
                source_id="source",
                external_id="race-a",
                canonical_url="https://example.test/race-a",
                payload={},
                title="OpenAI launches Race AI model",
                title_fingerprint="openai-launches-race-ai-model",
                published_at=now,
            )
        )
        _seed_operation(db, 301, window_end=now)
        _seed_operation(db, 302, window_end=now)
        db.commit()
        first = EventPipeline.production(db).run(
            window_hours=24, operation_id=301, checkpoint=lambda _: None
        )
        event_id = first.current_event_ids[0]
        db.add(
            RawItemRecord(
                source_id="source",
                external_id="race-b",
                canonical_url="https://example.test/race-b",
                payload={},
                title="OpenAI launches Race AI model",
                title_fingerprint="openai-launches-race-ai-model",
                published_at=now,
            )
        )
        db.commit()

    original_claim = EventRepository.claim_event
    injected = False

    def inject_a_winner_then_claim(self, claimed_event_id, operation_id, lease_until):
        nonlocal injected
        if not injected:
            injected = True
            record = self.session.get(EventRecord, claimed_event_id)
            previous = self.session.scalar(
                select(EventVersionRecord).where(
                    EventVersionRecord.event_id == claimed_event_id,
                    EventVersionRecord.version_number == 1,
                )
            )
            previous_score = self.session.scalar(
                select(EventScoreRecord).where(
                    EventScoreRecord.event_id == claimed_event_id,
                    EventScoreRecord.version_number == 1,
                )
            )
            second_item_id = self.session.scalar(
                select(RawItemRecord.id).where(RawItemRecord.external_id == "race-b")
            )
            assert record and previous and previous_score and second_item_id
            payload = dict(previous.payload)
            payload["source_item_ids"] = [1, second_item_id]
            self.session.add(
                EventVersionRecord(
                    event_id=claimed_event_id,
                    version_number=2,
                    payload=payload,
                    zh_title=previous.zh_title,
                    zh_summary=previous.zh_summary,
                )
            )
            self.session.add(
                EventItemRecord(
                    event_id=claimed_event_id,
                    raw_item_id=second_item_id,
                    added_version_number=2,
                )
            )
            self.session.add(
                EventScoreRecord(
                    event_id=claimed_event_id,
                    version_number=2,
                    heat=previous_score.heat,
                    breakdown=previous_score.breakdown,
                )
            )
            record.current_version_number = 2
            self.session.flush()
        return original_claim(self, claimed_event_id, operation_id, lease_until)

    monkeypatch.setattr(EventRepository, "claim_event", inject_a_winner_then_claim)
    with Session(engine) as db:
        second = EventPipeline.production(db).run(
            window_hours=24, operation_id=302, checkpoint=lambda _: None
        )
        assert second.created_event_versions == 0
        assert db.get(EventRecord, event_id).current_version_number == 2  # type: ignore[union-attr]
        assert db.query(EventVersionRecord).filter_by(event_id=event_id).count() == 2
        assert db.query(EventModelRunRecord).filter_by(event_id=event_id).count() == 2


def test_pipeline_returns_retryable_conflict_when_publication_lease_is_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add(_source_record())
        db.add(
            RawItemRecord(
                source_id="source",
                external_id="first-lease",
                canonical_url="https://example.test/first-lease",
                payload={},
                title="OpenAI launches Lease AI model",
                title_fingerprint="openai-launches-lease-ai-model",
                published_at=now,
            )
        )
        _seed_operation(db, 201, window_end=now)
        _seed_operation(db, 202, window_end=now)
        db.commit()
        EventPipeline.production(db).run(
            window_hours=24,
            operation_id=201,
            checkpoint=lambda _: None,
        )
        db.add(
            RawItemRecord(
                source_id="source",
                external_id="second-lease",
                canonical_url="https://example.test/second-lease",
                payload={},
                title="OpenAI launches Lease AI model",
                title_fingerprint="openai-launches-lease-ai-model",
                published_at=now,
            )
        )
        db.commit()

    monkeypatch.setattr(EventRepository, "claim_event", lambda *args: False)
    with Session(engine) as db:
        with pytest.raises(EventPublicationConflict, match="lease") as raised:
            EventPipeline.production(db).run(
                window_hours=24,
                operation_id=202,
                checkpoint=lambda _: None,
            )

    assert raised.value.retryable is True


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
        _seed_operation(db, 1)
        db.commit()
        event_id = (
            EventPipeline.production(db)
            .run(window_hours=24, operation_id=1, checkpoint=lambda _: None)
            .current_event_ids[0]
        )

        detail = EventQueryService(db).get_event(event_id)
        version = db.scalar(
            select(EventVersionRecord).where(
                EventVersionRecord.event_id == event_id,
                EventVersionRecord.version_number == 1,
            )
        )

    assert detail is not None
    assert detail.evidence[0].role == "official"
    assert detail.evidence[0].root_evidence_key == "https://example.test/official-1"
    assert detail.evidence[0].independent is True
    assert detail.evidence[0].limitations == ()
    assert version is not None
    assert version.payload["status"] == "confirmed"
    assert version.payload["evidence_summary"] == {
        "official_roots": 1,
        "professional_roots": 0,
        "community_signals": 0,
        "aggregator_pointers": 0,
        "missing_confirmation": [],
    }


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
        _seed_operation(db, 1)
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
        _seed_operation(db, 2)
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
    tmp_path,
) -> None:
    database_path = (tmp_path / "model-transaction-boundary.db").as_posix()
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
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
        _seed_operation(db, 1)
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
        _seed_operation(db, 2)
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
        _seed_operation(db, 3)
        db.commit()

    with Session(engine) as db:
        result = EventPipeline.production(db).run(
            window_hours=24, operation_id=3, checkpoint=lambda _: None
        )

    assert result.duplicate_root_suppressed_count == 1
