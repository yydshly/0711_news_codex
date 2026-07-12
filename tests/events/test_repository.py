from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from newsradar.db.models import Base, RawItemRecord, SourceDefinitionRecord
from newsradar.events.repository import EventRepository
from newsradar.events.schema import ProcessingStage


def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def raw_item(db: Session) -> RawItemRecord:
    db.add(
        SourceDefinitionRecord(
            id="source",
            name="Source",
            nature="publisher",
            language="en",
            roles=[],
            topics=[],
            authority_score=1,
            poll_interval_minutes=60,
            expected_fields=[],
            definition_hash="hash",
        )
    )
    item = RawItemRecord(
        source_id="source",
        external_id="item",
        canonical_url="https://example.test/item",
        payload={},
    )
    db.add(item)
    db.commit()
    return item


def test_stage_record_is_idempotent() -> None:
    with session() as db:
        item = raw_item(db)
        repository = EventRepository(db)

        first = repository.record_stage(item.id, ProcessingStage.RELEVANCE, "relevance-v1")
        second = repository.record_stage(item.id, ProcessingStage.RELEVANCE, "relevance-v1")
        db.commit()

        assert first.id == second.id


def test_claim_statement_uses_conditional_live_lease_guard() -> None:
    with session() as db:
        statement = EventRepository(db)._claim_statement(
            event_id=1,
            operation_id=2,
            lease_until=datetime.now(UTC) + timedelta(minutes=1),
        )

        compiled = str(statement.compile(dialect=postgresql.dialect()))

        assert "UPDATE events" in compiled
        assert "lease_expires_at" in compiled
