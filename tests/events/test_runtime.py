from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import Base, EventRecord, RawItemRecord, SourceDefinitionRecord
from newsradar.events.repository import EventRepository
from newsradar.events.runtime import EventOperationHandler
from newsradar.operations.deadlines import OperationDeadline, OperationTimedOut
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


def test_recluster_action_is_completed_by_the_worker() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(EventRecord(id=1, canonical_key="one", status="confirmed"))
        db.commit()

    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(1, 1, 1, "worker", {"event_id": 1, "actor": "web"}, "event_recluster"),
        lambda _: None,
    )

    assert result.status is OperationStatus.SUCCEEDED
    assert result.result_summary["action"] == "event_recluster"


def test_exclude_action_marks_event_rejected_and_releases_lease() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(EventRecord(id=7, canonical_key="exclude", status="confirmed"))
        db.commit()

    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(1, 9, 1, "worker", {"event_id": 7, "actor": "web"}, "event_exclude"),
        lambda _: None,
    )

    with Session(engine) as db:
        event = db.get(EventRecord, 7)
        assert event is not None
        assert event.status == "rejected"
        assert event.lease_operation_id is None
    assert result.status is OperationStatus.SUCCEEDED


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


def test_expired_event_action_mutates_nothing() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(EventRecord(id=8, canonical_key="deadline", status="confirmed"))
        db.commit()
    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(
            1, 1, 1, "worker",
            {
                "event_id": 8,
                "actor": "web",
                "deadline_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            },
            "event_exclude",
        ), lambda _: None,
    )
    with Session(engine) as db:
        assert db.get(EventRecord, 8).status == "confirmed"
    assert result.error_code == "operation_timeout"


def test_merge_claims_both_events_in_sorted_order_and_releases_in_reverse(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                EventRecord(id=1, canonical_key="target", status="confirmed"),
                EventRecord(id=2, canonical_key="survivor", status="confirmed"),
            ]
        )
        db.commit()

    order: list[tuple[str, int]] = []
    original_claim = EventRepository.claim_event
    original_release = EventRepository.release_event

    def observe_claim(self, event_id, operation_id, lease_until):
        order.append(("claim", event_id))
        return original_claim(self, event_id, operation_id, lease_until)

    def observe_release(self, event_id, operation_id):
        order.append(("release", event_id))
        return original_release(self, event_id, operation_id)

    monkeypatch.setattr(EventRepository, "claim_event", observe_claim)
    monkeypatch.setattr(EventRepository, "release_event", observe_release)
    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(
            1,
            51,
            1,
            "worker",
            {"event_id": 2, "target_event_id": 1, "actor": "web"},
            "event_merge",
        ),
        lambda _: None,
    )

    assert result.status is OperationStatus.SUCCEEDED
    assert order == [("claim", 1), ("claim", 2), ("release", 2), ("release", 1)]
    with Session(engine) as db:
        assert db.get(EventRecord, 1).lease_operation_id is None
        assert db.get(EventRecord, 2).lease_operation_id is None


def test_merge_releases_first_lease_when_second_claim_fails(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                EventRecord(id=1, canonical_key="survivor", status="confirmed"),
                EventRecord(id=2, canonical_key="busy", status="confirmed"),
            ]
        )
        db.commit()

    order: list[tuple[str, int]] = []
    original_claim = EventRepository.claim_event
    original_release = EventRepository.release_event

    def fail_second_claim(self, event_id, operation_id, lease_until):
        order.append(("claim", event_id))
        if event_id == 2:
            return False
        return original_claim(self, event_id, operation_id, lease_until)

    def observe_release(self, event_id, operation_id):
        order.append(("release", event_id))
        return original_release(self, event_id, operation_id)

    monkeypatch.setattr(EventRepository, "claim_event", fail_second_claim)
    monkeypatch.setattr(EventRepository, "release_event", observe_release)
    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(
            1,
            52,
            1,
            "worker",
            {"event_id": 1, "target_event_id": 2, "actor": "web"},
            "event_merge",
        ),
        lambda _: None,
    )

    assert result.error_code == "event_lease_unavailable"
    assert order == [("claim", 1), ("claim", 2), ("release", 1)]
    with Session(engine) as db:
        assert db.get(EventRecord, 1).lease_operation_id is None


def test_deadline_after_merge_claim_releases_both_leases_and_returns_timeout(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                EventRecord(id=1, canonical_key="survivor", status="confirmed"),
                EventRecord(id=2, canonical_key="target", status="confirmed"),
            ]
        )
        db.commit()

    class DeadlineAfterClaims:
        def check(self, boundary: str) -> None:
            if boundary == "before_event_mutation":
                raise OperationTimedOut("operation deadline exceeded at before_event_mutation")

    monkeypatch.setattr(
        OperationDeadline,
        "from_scope",
        classmethod(lambda cls, scope: DeadlineAfterClaims()),
    )

    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(
            1,
            53,
            1,
            "worker",
            {
                "event_id": 1,
                "target_event_id": 2,
                "actor": "web",
                "deadline_at": datetime.now(UTC).isoformat(),
            },
            "event_merge",
        ),
        lambda _: None,
    )

    assert result.error_code == "operation_timeout"
    assert result.retryable is False
    with Session(engine) as db:
        for event_id in (1, 2):
            event = db.get(EventRecord, event_id)
            assert event is not None
            assert event.lease_operation_id is None
            assert event.current_version_number == 0
