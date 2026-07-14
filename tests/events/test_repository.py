from datetime import UTC, datetime, timedelta
from enum import Enum
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newsradar.ai.minimax import ModelUsage
from newsradar.db.models import (
    Base,
    EventCandidateItemRecord,
    EventItemRecord,
    EventRecord,
    EventVersionRecord,
    RawItemProcessingRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.repository import EventRepository
from newsradar.events.schema import (
    CandidateCluster,
    EntityType,
    EventCategory,
    EventStatus,
    EventVisibility,
    EvidenceRole,
    ProcessingStage,
    PublishedEvent,
    ScoreBreakdown,
)


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


def published_event(**changes: object) -> PublishedEvent:
    data: dict[str, object] = {
        "canonical_key": "release",
        "status": EventStatus.EMERGING,
        "score": ScoreBreakdown(
            ai_relevance=0,
            source_coverage=0,
            source_authority=0,
            recency=0,
            engagement_velocity=0,
            novelty=0,
            importance=0,
            credibility=0,
            heat=0,
            rule_version="score-v1",
            reasons=(),
        ),
    }
    data.update(changes)
    return PublishedEvent(**data)


def test_stage_record_is_idempotent() -> None:
    with session() as db:
        item = raw_item(db)
        repository = EventRepository(db)

        first = repository.record_stage(item.id, ProcessingStage.RELEVANCE, "relevance-v1")
        second = repository.record_stage(item.id, ProcessingStage.RELEVANCE, "relevance-v1")
        db.commit()

        assert first.id == second.id


def test_event_visibility_has_stable_current_and_legacy_values() -> None:
    assert EventVisibility.CURRENT.value == "current"
    assert EventVisibility.LEGACY.value == "legacy"


def test_complete_version_payload_contains_only_safe_current_model_run_summary() -> None:
    with session() as db:
        repository = EventRepository(db)
        usage = ModelUsage(
            purpose="event_enrichment",
            model="MiniMax-M2.7-highspeed",
            input_tokens=123,
            output_tokens=45,
            latency_ms=87.5,
            outcome="success",
            error="Authorization: Bearer must-not-enter-version",
        )

        event = repository.publish_complete_event(
            published_event(), operation_id=1, model_usages=(usage,)
        )
        db.commit()

        version = db.scalar(
            select(EventVersionRecord).where(EventVersionRecord.event_id == event.id)
        )
        assert version.payload["model_runs"] == [
            {
                "model": "MiniMax-M2.7-highspeed",
                "purpose": "event_enrichment",
                "outcome": "success",
                "latency_ms": 87.5,
            }
        ]
        serialized = repr(version.payload)
        assert "input_tokens" not in serialized
        assert "output_tokens" not in serialized
        assert "Authorization" not in serialized


def test_stage_record_updates_the_same_processing_decision() -> None:
    with session() as db:
        item = raw_item(db)
        repository = EventRepository(db)

        first = repository.record_stage(
            item.id,
            ProcessingStage.RELEVANCE,
            "relevance-v2",
            outcome="included",
            score=82,
            reason_codes=("ai_product_action",),
            details={"threshold": 60, "matched": True},
        )
        second = repository.record_stage(
            item.id,
            ProcessingStage.RELEVANCE,
            "relevance-v2",
            outcome="excluded",
            score=18,
            reason_codes=("off_topic",),
            details={"threshold": 60, "matched": False, "visibility": EventVisibility.LEGACY},
        )
        db.commit()

        records = db.scalars(select(RawItemProcessingRecord)).all()
        assert first.id == second.id
        assert len(records) == 1
        assert records[0].outcome == "excluded"
        assert records[0].score == 18
        assert records[0].reason_codes == ["off_topic"]
        assert records[0].details == {
            "threshold": 60,
            "matched": False,
            "visibility": "legacy",
        }


@pytest.mark.parametrize(
    "details",
    [
        {"body": "full article text"},
        {"url": "https://example.test/private"},
        {"request_headers": {"Authorization": "secret"}},
    ],
)
def test_stage_record_rejects_sensitive_processing_details(details: dict[str, object]) -> None:
    with session() as db:
        item = raw_item(db)

        with pytest.raises(ValueError, match="booleans, numbers, or enum members"):
            EventRepository(db).record_stage(
                item.id,
                ProcessingStage.RELEVANCE,
                "relevance-v2",
                details=details,
            )


@pytest.mark.parametrize(
    "key",
    [
        "API-Key",
        "access_token",
        "AUTHORIZATION",
        "session-cookie",
        "client_secret",
        "service-Credential",
        "db_password",
        "request_headers",
    ],
)
def test_stage_record_rejects_sensitive_detail_keys_even_for_safe_enum_values(key: str) -> None:
    with session() as db:
        item = raw_item(db)

        with pytest.raises(ValueError, match="sensitive field names"):
            EventRepository(db).record_stage(
                item.id,
                ProcessingStage.RELEVANCE,
                "relevance-v2",
                details={key: EventVisibility.LEGACY},
            )


@pytest.mark.parametrize(
    "value",
    [
        EventVisibility.LEGACY,
        EventStatus.CONFIRMED,
        ProcessingStage.RELEVANCE,
        EventCategory.RESEARCH,
        EvidenceRole.OFFICIAL,
        EntityType.MODEL,
    ],
)
def test_stage_record_accepts_project_defined_stable_audit_enums(value: Enum) -> None:
    with session() as db:
        item = raw_item(db)

        record = EventRepository(db).record_stage(
            item.id,
            ProcessingStage.RELEVANCE,
            "relevance-v2",
            details={"decision": value},
        )

        assert record.details == {"decision": value.value}


@pytest.mark.parametrize(
    "details",
    [
        {"matched_token_count": 3},
        {"header_present": False},
    ],
)
def test_stage_record_accepts_safe_metric_detail_keys(details: dict[str, object]) -> None:
    with session() as db:
        item = raw_item(db)

        record = EventRepository(db).record_stage(
            item.id,
            ProcessingStage.RELEVANCE,
            "relevance-v2",
            details=details,
        )

        assert record.details == details


def test_stage_record_rejects_credential_bearing_string_enum() -> None:
    class CredentialEnum(Enum):
        TOKEN = "secret-token-value"

    with session() as db:
        item = raw_item(db)

        with pytest.raises(ValueError, match="project-defined stable enum"):
            EventRepository(db).record_stage(
                item.id,
                ProcessingStage.RELEVANCE,
                "relevance-v2",
                details={"decision": CredentialEnum.TOKEN},
            )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_stage_record_rejects_non_finite_enum_numbers(value: float) -> None:
    class NonFiniteEnum(Enum):
        VALUE = value

    with session() as db:
        item = raw_item(db)

        with pytest.raises(ValueError, match="finite numbers"):
            EventRepository(db).record_stage(
                item.id,
                ProcessingStage.RELEVANCE,
                "relevance-v2",
                details={"threshold": NonFiniteEnum.VALUE},
            )


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


def test_candidate_upsert_replaces_membership_and_updates_timestamp() -> None:
    with session() as db:
        first_item = raw_item(db)
        second_item = RawItemRecord(
            source_id="source",
            external_id="item-2",
            canonical_url="https://example.test/item-2",
            payload={},
        )
        db.add(second_item)
        db.commit()
        repository = EventRepository(db)
        candidate = repository.upsert_candidate(
            CandidateCluster(candidate_key="release", title="Initial"), "cluster-v1"
        )
        candidate.updated_at = datetime(2000, 1, 1)
        repository.replace_candidate_items(candidate.id, (first_item.id,))
        db.commit()

        updated = repository.upsert_candidate(
            CandidateCluster(candidate_key="release", title="Updated"), "cluster-v1"
        )
        repository.replace_candidate_items(updated.id, (second_item.id,))
        db.commit()

        assert updated.id == candidate.id
        assert updated.updated_at > datetime(2000, 1, 1)
        membership = db.scalars(select(EventCandidateItemRecord)).all()
        assert [item.raw_item_id for item in membership] == [second_item.id]


def test_event_update_publishing_claim_and_release_are_durable() -> None:
    with session() as db:
        item = raw_item(db)
        repository = EventRepository(db)
        initial = PublishedEvent(canonical_key="release", status=EventStatus.EMERGING)
        event = repository.create_or_update_event(initial)
        event.updated_at = datetime(2000, 1, 1)
        db.commit()

        updated = repository.create_or_update_event(
            PublishedEvent(
                event_id=event.id,
                canonical_key="release",
                status=EventStatus.CONFIRMED,
                source_item_ids=(item.id,),
            )
        )
        repository.publish_complete_event(published_event(), operation_id=1)
        repository.publish_complete_event(
            published_event(status=EventStatus.CONFIRMED, source_item_ids=(item.id,)),
            operation_id=1,
        )
        db.commit()

        assert updated.updated_at > datetime(2000, 1, 1)
        versions = db.scalars(select(EventVersionRecord)).all()
        assert [version.version_number for version in versions] == [1, 2]
        assert db.get(EventRecord, updated.id).current_version_number == 2  # type: ignore[union-attr]
        assert db.scalars(select(EventItemRecord)).all()[0].removed_version_number is None
        assert repository.claim_event(updated.id, 1, datetime.now(UTC) + timedelta(minutes=1))
        assert not repository.claim_event(updated.id, 2, datetime.now(UTC) + timedelta(minutes=1))
        assert not repository.release_event(updated.id, 2)
        assert repository.release_event(updated.id, 1)
        assert db.get(EventRecord, updated.id).lease_expires_at is None  # type: ignore[union-attr]


def test_repeated_stage_and_candidate_upserts_use_unique_keys() -> None:
    with session() as db:
        item = raw_item(db)
        repository = EventRepository(db)

        first_stage = repository.record_stage(item.id, ProcessingStage.RELEVANCE, "v1")
        second_stage = repository.record_stage(item.id, ProcessingStage.RELEVANCE, "v1")
        first_candidate = repository.upsert_candidate(CandidateCluster(candidate_key="key"), "v1")
        second_candidate = repository.upsert_candidate(CandidateCluster(candidate_key="key"), "v1")

        assert first_stage.id == second_stage.id
        assert first_candidate.id == second_candidate.id


def test_publishing_closes_removed_memberships_and_readds_as_new_rows() -> None:
    with session() as db:
        first = raw_item(db)
        second = RawItemRecord(
            source_id="source",
            external_id="item-2",
            canonical_url="https://example.test/item-2",
            payload={},
        )
        db.add(second)
        db.commit()
        repository = EventRepository(db)
        repository.create_or_update_event(
            PublishedEvent(canonical_key="release", status=EventStatus.EMERGING)
        )

        repository.publish_complete_event(
            published_event(source_item_ids=(first.id, second.id)), operation_id=1
        )
        repository.publish_complete_event(
            published_event(source_item_ids=(first.id,)), operation_id=1
        )
        memberships = db.scalars(select(EventItemRecord).order_by(EventItemRecord.id)).all()
        assert [(item.raw_item_id, item.removed_version_number) for item in memberships] == [
            (first.id, None),
            (second.id, 2),
        ]

        repository.publish_complete_event(published_event(), operation_id=1)
        repository.publish_complete_event(
            published_event(source_item_ids=(first.id,)), operation_id=1
        )
        active = db.scalars(
            select(EventItemRecord).where(EventItemRecord.removed_version_number.is_(None))
        ).all()
        assert len(active) == 1
        assert active[0].raw_item_id == first.id
        first_memberships = db.scalars(
            select(EventItemRecord).where(EventItemRecord.raw_item_id == first.id)
        ).all()
        assert len(first_memberships) == 2


def test_insert_rejects_unsupported_database_dialect() -> None:
    session_stub = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="mysql")))
    repository = EventRepository(session_stub)

    with pytest.raises(ValueError, match="Unsupported event repository dialect: mysql"):
        repository._insert(EventRecord)


def test_publish_does_not_swallow_unrelated_integrity_error() -> None:
    class OtherConstraintError(Exception):
        diag = SimpleNamespace(
            constraint_name="event_versions_event_id_version_number_key"
        )

    with session() as db:
        def fail_unrelated_constraint(session, flush_context, instances) -> None:
            del flush_context, instances
            if any(isinstance(row, EventRecord) for row in session.new):
                raise IntegrityError(
                    "INSERT INTO events",
                    {},
                    OtherConstraintError("unrelated unique violation"),
                )

        sqlalchemy_event.listen(db, "before_flush", fail_unrelated_constraint)

        with pytest.raises(IntegrityError, match="unrelated unique violation"):
            EventRepository(db).publish_complete_event(
                published_event(), operation_id=1
            )
