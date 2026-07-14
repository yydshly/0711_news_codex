from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from newsradar.ai.minimax import ModelUsage
from newsradar.db.models import (
    Base,
    EventModelRunRecord,
    ModelUsageRecord,
    OperationRunRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.minimax import EventModelRun
from newsradar.events.pipeline import EventPipeline
from newsradar.events.publishing import rule_enrichment
from newsradar.events.repository import EventRepository
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

    def enrichment(candidate):
        fallback = rule_enrichment(candidate)
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
        return result, (EventModelRun(stage=usage.purpose, usage=usage),)

    monkeypatch.setattr(EventPipeline, "_enrich", staticmethod(enrichment))
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

    def enrichment(candidate):
        fallback = rule_enrichment(candidate).model_copy(update={"origin": "model"})
        usage = ModelUsage(
            purpose="event_enrichment",
            model="MiniMax-M2.7-highspeed",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            outcome="success",
        )
        return fallback, (EventModelRun(stage=usage.purpose, usage=usage),)

    monkeypatch.setattr(EventPipeline, "_enrich", staticmethod(enrichment))
    with Session(engine) as db:
        event_id = EventPipeline.production(db).run(
            window_hours=24, operation_id=42, checkpoint=lambda _: None
        ).current_event_ids[0]
    with Session(engine) as db:
        detail = EventQueryService(db).get_event(event_id)

    assert detail is not None
    assert detail.model_versions == ("MiniMax-M2.7-highspeed",)
    assert detail.minimax_degraded is False


def test_model_provenance_sink_failure_does_not_block_publication(monkeypatch) -> None:
    engine = _engine_with_candidate()

    def enrichment(candidate):
        usage = ModelUsage(
            purpose="event_enrichment",
            model="MiniMax-M2.7-highspeed",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            outcome="success",
        )
        return rule_enrichment(candidate), (EventModelRun(stage=usage.purpose, usage=usage),)

    def fail_sink(self, event_id, usage):
        del self, event_id, usage
        raise RuntimeError("provenance database unavailable")

    monkeypatch.setattr(EventPipeline, "_enrich", staticmethod(enrichment))
    monkeypatch.setattr(EventRepository, "record_model_run", fail_sink)
    with Session(engine) as db:
        result = EventPipeline.production(db).run(
            window_hours=24, operation_id=43, checkpoint=lambda _: None
        )

    assert result.created_event_versions == 1
    with Session(engine) as db:
        detail = EventQueryService(db).get_event(result.current_event_ids[0])
        assert detail is not None
        assert db.scalar(select(ModelUsageRecord)) is None
        assert db.scalar(select(EventModelRunRecord)) is None
