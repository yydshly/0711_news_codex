from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import Base, EventRecord, RawItemRecord, SourceDefinitionRecord
from newsradar.events.runtime import EventOperationHandler
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus


def test_event_handler_rejects_invalid_pipeline_scope() -> None:
    handler = EventOperationHandler(lambda: None)
    result = handler(OperationLease(1, 1, 1, "worker", {}, "event_pipeline"), lambda _: None)

    assert result.status is OperationStatus.FAILED
    assert result.error_code == "invalid_event_scope"


def test_event_action_rejects_unknown_event_id() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    handler = EventOperationHandler(lambda: Session(engine))

    result = handler(
        OperationLease(1, 1, 1, "worker", {"event_id": 99}, "event_exclude"), lambda _: None
    )

    assert result.status is OperationStatus.FAILED
    assert result.error_code == "unknown_event"
    assert result.retryable is False


def test_supported_web_action_is_nonretryable_until_its_mutation_is_implemented() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(EventRecord(id=1, canonical_key="one", status="confirmed"))
        db.commit()

    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(1, 1, 1, "worker", {"event_id": 1, "actor": "web"}, "event_recluster"),
        lambda _: None,
    )

    assert result.status is OperationStatus.FAILED
    assert result.error_code == "unsupported_action"
    assert result.retryable is False


def test_merge_validates_both_event_targets_before_returning_unsupported() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(EventRecord(id=1, canonical_key="one", status="confirmed"))
        db.commit()

    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(
            1,
            1,
            1,
            "worker",
            {"event_id": 1, "target_event_id": 2, "actor": "web"},
            "event_merge",
        ),
        lambda _: None,
    )

    assert result.error_code == "unknown_event"


def test_expired_event_pipeline_returns_timeout_without_publishing() -> None:
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
                external_id="item",
                canonical_url="https://example.test/item",
                payload={},
                title="OpenAI launches model",
                published_at=datetime.now(UTC),
            )
        )
        db.commit()

    handler = EventOperationHandler(lambda: Session(engine))
    result = handler(
        OperationLease(
            1,
            1,
            1,
            "worker",
            {
                "window_hours": 24,
                "deadline_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            },
            "event_pipeline",
        ),
        lambda _: None,
    )

    with Session(engine) as verify:
        assert verify.query(EventRecord).count() == 0
    assert result.status is OperationStatus.FAILED
    assert result.error_code == "operation_timeout"
    assert result.retryable is False
