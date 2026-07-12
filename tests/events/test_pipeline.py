from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import Base, EventVersionRecord, RawItemRecord, SourceDefinitionRecord
from newsradar.events.pipeline import EventPipeline


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
