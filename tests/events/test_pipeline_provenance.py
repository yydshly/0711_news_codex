from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from newsradar.ai.minimax import ModelUsage
from newsradar.db.models import (
    Base,
    EventModelRunRecord,
    EventRecord,
    ModelUsageRecord,
    OperationRunRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.minimax import EventEnrichmentResult, EventModelRun
from newsradar.events.pipeline import EventModelAuditError, EventPipeline
from newsradar.events.publishing import rule_enrichment
from newsradar.events.repository import EventRepository
from newsradar.settings import Settings
from newsradar.web.event_queries import EventQueryService


def _engine_with_candidate():
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
                external_id="release",
                canonical_url="https://official.test/release",
                payload={},
                title="OpenAI launches Orion model",
                published_at=datetime.now(UTC),
            )
        )
        snapshot = datetime.now(UTC)
        db.add_all(
            OperationRunRecord(
                id=operation_id,
                operation_type="event_pipeline",
                trigger="manual",
                status="running",
                requested_scope={"window_end": snapshot.isoformat()},
                created_at=snapshot,
            )
            for operation_id in (41, 42, 43)
        )
        db.commit()
    return engine


@pytest.mark.parametrize(
    ("outcome", "origin", "error"),
    [("success", "model", None), ("fallback", "rule_fallback", "timeout")],
)
def test_pipeline_persists_model_usage_and_linked_event_run(
    monkeypatch, outcome: str, origin: str, error: str | None
) -> None:
    engine = _engine_with_candidate()

    async def enrichment(candidate, fallback, settings, http):
        del candidate, settings, http
        result = fallback.model_copy(update={"origin": origin})
        usage = ModelUsage(
            purpose="event_enrichment",
            model="MiniMax-M2.7-highspeed",
            input_tokens=31,
            output_tokens=17,
            latency_ms=12.5,
            outcome=outcome,
            error=error,
        )
        return EventEnrichmentResult(
            enrichment=result,
            model_runs=(EventModelRun(stage=usage.purpose, usage=usage),),
        )

    monkeypatch.setattr(EventPipeline, "_enrich_candidate_async", staticmethod(enrichment))
    with Session(engine) as db:
        event_id = EventPipeline.production(db).run(
            window_hours=24, operation_id=41, checkpoint=lambda _: None
        ).current_event_ids[0]

    with Session(engine) as db:
        usage = db.scalar(select(ModelUsageRecord))
        run = db.scalar(select(EventModelRunRecord))
        assert usage is not None
        assert usage.outcome == outcome
        assert usage.error == error
        assert usage.input_tokens == 31
        assert usage.output_tokens == 17
        assert run is not None
        assert run.event_id == event_id
        assert run.model_usage_id == usage.id
        assert run.stage == "event_enrichment"


def test_event_detail_projects_persisted_model_provenance(monkeypatch) -> None:
    engine = _engine_with_candidate()

    async def enrichment(candidate, fallback, settings, http):
        del candidate, settings, http
        fallback = fallback.model_copy(update={"origin": "model"})
        usage = ModelUsage(
            purpose="event_enrichment",
            model="MiniMax-M2.7-highspeed",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            outcome="success",
        )
        return EventEnrichmentResult(
            enrichment=fallback,
            model_runs=(EventModelRun(stage=usage.purpose, usage=usage),),
        )

    monkeypatch.setattr(EventPipeline, "_enrich_candidate_async", staticmethod(enrichment))
    with Session(engine) as db:
        event_id = EventPipeline.production(db).run(
            window_hours=24, operation_id=42, checkpoint=lambda _: None
        ).current_event_ids[0]
    with Session(engine) as db:
        detail = EventQueryService(db).get_event(event_id)

    assert detail is not None
    assert detail.model_versions == ("MiniMax-M2.7-highspeed",)
    assert detail.minimax_degraded is False


def test_model_provenance_sink_failure_rolls_back_publication_and_is_retryable(
    monkeypatch,
) -> None:
    engine = _engine_with_candidate()

    async def enrichment(candidate, fallback, settings, http):
        del fallback, settings, http
        usage = ModelUsage(
            purpose="event_enrichment",
            model="MiniMax-M2.7-highspeed",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            outcome="success",
        )
        return EventEnrichmentResult(
            enrichment=rule_enrichment(candidate),
            model_runs=(EventModelRun(stage=usage.purpose, usage=usage),),
        )

    def fail_sink(self, event_id, usage):
        del self, event_id, usage
        raise RuntimeError("provenance database unavailable")

    monkeypatch.setattr(EventPipeline, "_enrich_candidate_async", staticmethod(enrichment))
    monkeypatch.setattr(EventRepository, "record_model_run", fail_sink)
    with Session(engine) as db, pytest.raises(EventModelAuditError) as raised:
        EventPipeline.production(db).run(
            window_hours=24, operation_id=43, checkpoint=lambda _: None
        )

    assert raised.value.retryable is True
    with Session(engine) as db:
        assert db.scalar(select(EventRecord)) is None
        assert db.scalar(select(ModelUsageRecord)) is None
        assert db.scalar(select(EventModelRunRecord)) is None


def test_pipeline_links_every_repair_attempt_to_the_final_event(monkeypatch) -> None:
    engine = _engine_with_candidate()

    async def enrichment(candidate, fallback, settings, http):
        del candidate, settings, http
        fallback = fallback.model_copy(update={"origin": "model"})
        usages = (
            ModelUsage(
                purpose="event_enrichment",
                model="MiniMax-M2.7-highspeed",
                input_tokens=10,
                output_tokens=3,
                latency_ms=2,
                outcome="retry",
                error="invalid_response",
            ),
            ModelUsage(
                purpose="event_enrichment",
                model="MiniMax-M2.7-highspeed",
                input_tokens=11,
                output_tokens=4,
                latency_ms=3,
                outcome="success",
            ),
        )
        return EventEnrichmentResult(
            enrichment=fallback,
            model_runs=tuple(
                EventModelRun(stage=usage.purpose, usage=usage) for usage in usages
            ),
        )

    monkeypatch.setattr(EventPipeline, "_enrich_candidate_async", staticmethod(enrichment))
    with Session(engine) as db:
        result = EventPipeline.production(db).run(
            window_hours=24, operation_id=41, checkpoint=lambda _: None
        )
        event_id = result.current_event_ids[0]

    with Session(engine) as db:
        usages = tuple(db.scalars(select(ModelUsageRecord).order_by(ModelUsageRecord.id)))
        runs = tuple(db.scalars(select(EventModelRunRecord).order_by(EventModelRunRecord.id)))

    assert [usage.outcome for usage in usages] == ["retry", "success"]
    assert [usage.error for usage in usages] == ["invalid_response", None]
    assert result.model_error_counts == {"invalid_response": 1}
    assert len(runs) == 2
    assert {run.event_id for run in runs} == {event_id}
    assert [run.model_usage_id for run in runs] == [usage.id for usage in usages]


def test_pipeline_persists_safe_no_api_key_usage_without_network(monkeypatch) -> None:
    engine = _engine_with_candidate()
    monkeypatch.setattr(
        "newsradar.events.pipeline.get_settings",
        lambda: Settings(minimax_api_key=None),
    )

    with Session(engine) as db:
        result = EventPipeline.production(db).run(
            window_hours=24, operation_id=41, checkpoint=lambda _: None
        )
        event_id = result.current_event_ids[0]

    with Session(engine) as db:
        usage = db.scalar(select(ModelUsageRecord))
        run = db.scalar(select(EventModelRunRecord))

    assert usage is not None
    assert usage.outcome == "fallback"
    assert usage.error == "no_api_key"
    assert result.model_error_counts == {"no_api_key": 1}
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert "Bearer" not in repr(usage.error)
    assert "?" not in usage.error
    assert run is not None
    assert run.event_id == event_id
    assert run.model_usage_id == usage.id
