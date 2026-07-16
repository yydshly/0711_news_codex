from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, create_engine, event, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    EventMergeCandidateRecord,
    EventRecord,
    EventVersionRecord,
    OperationRunRecord,
)
from newsradar.event_merges import (
    EventMergeFacts,
    MergeCandidateDraft,
    MergeCandidateStatus,
    MergeCandidateType,
)
from newsradar.event_merges.repository import EventMergeCandidateRepository

NOW = datetime(2026, 7, 16, 4, 0, tzinfo=UTC)


@pytest.fixture
def engine() -> Iterator[Engine]:
    db_engine = create_engine("sqlite:///:memory:")

    @event.listens_for(db_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(db_engine)
    try:
        yield db_engine
    finally:
        db_engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as db_session:
        seed_references(db_session)
        yield db_session


def seed_references(session: Session) -> None:
    session.add_all(
        [
            EventRecord(
                id=3,
                canonical_key="event-3",
                visibility="current",
                status="confirmed",
                current_version_number=4,
            ),
            EventRecord(
                id=9,
                canonical_key="event-9",
                visibility="current",
                status="confirmed",
                current_version_number=2,
            ),
            EventVersionRecord(event_id=3, version_number=4, payload={}),
            EventVersionRecord(event_id=9, version_number=2, payload={}),
        ]
    )
    for operation_id in (10, 11, 12):
        session.add(
            OperationRunRecord(
                id=operation_id,
                operation_type="event_merge_scan",
                trigger="test",
                status="succeeded",
                requested_scope={},
                result_summary={},
            )
        )
    session.flush()


def event_facts(*, event_id: int, version_number: int) -> EventMergeFacts:
    return EventMergeFacts(
        event_id=event_id,
        version_number=version_number,
        visibility="current",
        canonical_key=f"event-{event_id}",
        algorithm_versions=("events-v2",),
        raw_item_ids=(event_id * 10,),
        source_ids=(f"source-{event_id}",),
        publishers=(f"Publisher {event_id}",),
        published_at=(NOW,),
        safe_url_identities=(f"https://example.com/items/{event_id}",),
        strong_identities=(),
        object_entities=("NewsRadar",),
        actions=("released",),
        evidence_roots=(f"publisher:{event_id}",),
    )


def draft(
    candidate_type: MergeCandidateType = MergeCandidateType.MANUAL_REVIEW,
) -> MergeCandidateDraft:
    return MergeCandidateDraft(
        left=event_facts(event_id=9, version_number=2),
        right=event_facts(event_id=3, version_number=4),
        candidate_type=candidate_type,
        input_fingerprint="a" * 64,
        reason_codes=("same_object", "same_action"),
        zh_reason="对象和动作相同，但没有强身份，必须人工确认。",
        zh_next_action="核对两个事件的原始报道后确认或保持分开。",
    )


def test_repository_upsert_is_idempotent_for_same_versioned_input(session: Session) -> None:
    repository = EventMergeCandidateRepository(session)

    first = repository.upsert_candidate(draft(), 10)
    second = repository.upsert_candidate(draft(), 10)
    session.flush()

    assert first.id == second.id
    assert session.query(EventMergeCandidateRecord).count() == 1


def test_repository_locked_get_refreshes_identity_mapped_candidate(
    session: Session,
    engine: Engine,
) -> None:
    repository = EventMergeCandidateRepository(session)
    record = repository.upsert_candidate(draft(), 10)
    record_id = record.id
    session.commit()
    assert record.status == MergeCandidateStatus.PENDING.value
    with Session(engine) as concurrent_session:
        concurrent_session.execute(
            update(EventMergeCandidateRecord)
            .where(EventMergeCandidateRecord.id == record_id)
            .values(status=MergeCandidateStatus.DISMISSED.value)
        )
        concurrent_session.commit()
    assert record.status == MergeCandidateStatus.PENDING.value

    refreshed = repository.get(record_id, for_update=True)

    assert refreshed is not None
    assert refreshed.status == MergeCandidateStatus.DISMISSED.value


def test_repository_recheck_creates_one_revision_child_and_reuses_it(
    session: Session,
) -> None:
    repository = EventMergeCandidateRepository(session)
    parent = repository.upsert_candidate(draft(), 10)
    session.flush()

    child = repository.create_revision(
        parent.id,
        draft(),
        generated_operation_id=11,
        reason_code="event_merge_recheck_requested",
    )
    retried = repository.create_revision(
        parent.id,
        draft(),
        generated_operation_id=11,
        reason_code="event_merge_recheck_requested",
    )
    session.flush()

    assert retried.id == child.id
    assert parent.status == MergeCandidateStatus.EXPIRED.value
    assert child.status == MergeCandidateStatus.PENDING.value
    assert child.revision == 2
    assert child.supersedes_candidate_id == parent.id
    assert session.query(EventMergeCandidateRecord).count() == 2


@pytest.mark.parametrize("changed_field", ["version_number", "algorithm_version"])
def test_repository_recheck_rejects_changed_chain_identity(
    session: Session,
    changed_field: str,
) -> None:
    repository = EventMergeCandidateRepository(session)
    original = draft()
    parent = repository.upsert_candidate(original, 10)
    if changed_field == "version_number":
        changed = original.model_copy(
            update={
                "left": original.left.model_copy(
                    update={"version_number": original.left.version_number + 1}
                )
            }
        )
    else:
        changed = original.model_copy(update={"algorithm_version": "event-merge-v2"})

    with pytest.raises(ValueError, match="event_merge_revision_chain_changed"):
        repository.create_revision(
            parent.id,
            changed,
            generated_operation_id=11,
            reason_code="event_merge_recheck_requested",
        )

    assert parent.status == MergeCandidateStatus.PENDING.value
    assert session.query(EventMergeCandidateRecord).count() == 1


def test_repository_scan_reuses_latest_matching_revision(session: Session) -> None:
    repository = EventMergeCandidateRepository(session)
    parent = repository.upsert_candidate(draft(), 10)
    child = repository.create_revision(
        parent.id,
        draft(),
        generated_operation_id=11,
        reason_code="event_merge_recheck_requested",
    )
    session.flush()

    scanned = repository.upsert_candidate(draft(), 12)

    assert scanned.id == child.id
    assert scanned.revision == 2
    assert session.query(EventMergeCandidateRecord).count() == 2


def test_repository_scan_with_changed_fingerprint_reuses_existing_chain(
    session: Session,
) -> None:
    repository = EventMergeCandidateRepository(session)
    first_draft = draft()
    changed_draft = first_draft.model_copy(
        update={"input_fingerprint": "b" * 64}
    )
    parent = repository.upsert_candidate(first_draft, 10)
    child = repository.create_revision(
        parent.id,
        changed_draft,
        generated_operation_id=11,
        reason_code="event_merge_recheck_requested",
    )
    session.flush()

    scanned = repository.upsert_candidate(changed_draft, 12)

    assert scanned.id == child.id
    assert session.query(EventMergeCandidateRecord).count() == 2
    assert (
        session.query(EventMergeCandidateRecord)
        .filter(EventMergeCandidateRecord.supersedes_candidate_id.is_(None))
        .count()
        == 1
    )


def test_database_rejects_second_root_for_same_stable_chain(session: Session) -> None:
    repository = EventMergeCandidateRepository(session)
    first_draft = draft()
    changed_draft = first_draft.model_copy(
        update={"input_fingerprint": "b" * 64}
    )
    repository.upsert_candidate(first_draft, 10)
    session.flush()

    with pytest.raises(IntegrityError):
        session.execute(
            repository._insert(EventMergeCandidateRecord).values(
                repository._candidate_values(
                    changed_draft,
                    12,
                    revision=1,
                    supersedes_candidate_id=None,
                )
            )
        )


def test_repository_second_session_reuses_existing_revision_chain(
    session: Session,
    engine: Engine,
) -> None:
    repository = EventMergeCandidateRepository(session)
    first_draft = draft()
    changed_draft = first_draft.model_copy(
        update={"input_fingerprint": "b" * 64}
    )
    parent = repository.upsert_candidate(first_draft, 10)
    child = repository.create_revision(
        parent.id,
        changed_draft,
        generated_operation_id=11,
        reason_code="event_merge_recheck_requested",
    )
    child_id = child.id
    session.commit()

    with Session(engine) as second_session:
        scanned = EventMergeCandidateRepository(second_session).upsert_candidate(
            changed_draft, 12
        )
        second_session.commit()
        assert scanned.id == child_id

    assert session.query(EventMergeCandidateRecord).count() == 2


@pytest.mark.parametrize("terminal_status", ["expired", "applied"])
def test_repository_scan_reuses_terminal_latest_revision(
    session: Session,
    terminal_status: str,
) -> None:
    repository = EventMergeCandidateRepository(session)
    deterministic = draft(MergeCandidateType.DETERMINISTIC_MERGE)
    parent = repository.upsert_candidate(deterministic, 10)
    child = repository.create_revision(
        parent.id,
        deterministic,
        generated_operation_id=11,
        reason_code="event_merge_recheck_requested",
    )
    if terminal_status == "expired":
        repository.mark_expired(child.id, "event_merge_version_changed")
    else:
        repository.mark_applied(child.id, 12, {"status": "succeeded"})
    session.flush()

    scanned = repository.upsert_candidate(deterministic, 10)

    assert scanned.id == child.id
    assert scanned.status == terminal_status
    assert session.query(EventMergeCandidateRecord).count() == 2


def test_repository_upsert_stores_only_bounded_facts_and_copy(session: Session) -> None:
    record = EventMergeCandidateRepository(session).upsert_candidate(draft(), 10)
    session.flush()

    assert (record.left_event_id, record.right_event_id) == (3, 9)
    assert (record.left_version_number, record.right_version_number) == (4, 2)
    assert record.status == MergeCandidateStatus.PENDING.value
    assert record.generated_operation_id == 10
    assert record.revision == 1
    assert record.supersedes_candidate_id is None
    assert record.reason_codes == ["same_object", "same_action"]
    assert record.facts_snapshot == {
        "left": draft().left.model_dump(mode="json"),
        "right": draft().right.model_dump(mode="json"),
    }
    assert "payload" not in str(record.facts_snapshot).lower()


def test_repository_manual_candidate_must_be_confirmed_before_apply(session: Session) -> None:
    repository = EventMergeCandidateRepository(session)
    record = repository.upsert_candidate(draft(), 10)
    session.flush()

    with pytest.raises(ValueError, match="event_merge_invalid_transition"):
        repository.mark_applied(record.id, 11, {})


def test_repository_review_then_apply_records_operations_and_result(session: Session) -> None:
    repository = EventMergeCandidateRepository(session)
    candidate_id = repository.upsert_candidate(draft(), 10).id
    session.flush()

    reviewed = repository.mark_reviewed(
        candidate_id, MergeCandidateStatus.CONFIRMED, operation_id=11
    )
    applied = repository.mark_applied(candidate_id, operation_id=12, result={"survivor": 3})
    session.flush()

    assert reviewed is applied
    assert applied.status == MergeCandidateStatus.APPLIED.value
    assert applied.reviewed_operation_id == 11
    assert applied.reviewed_at is not None
    assert applied.applied_operation_id == 12
    assert applied.result_summary == {"survivor": 3}


def test_repository_deterministic_candidate_can_apply_while_pending(session: Session) -> None:
    repository = EventMergeCandidateRepository(session)
    candidate_id = repository.upsert_candidate(
        draft(MergeCandidateType.DETERMINISTIC_MERGE), 10
    ).id
    session.flush()

    record = repository.mark_applied(candidate_id, operation_id=11, result={"survivor": 3})

    assert record.status == MergeCandidateStatus.APPLIED.value


def test_repository_review_can_dismiss_pending_candidate(session: Session) -> None:
    repository = EventMergeCandidateRepository(session)
    candidate_id = repository.upsert_candidate(draft(), 10).id
    session.flush()

    record = repository.mark_reviewed(
        candidate_id, MergeCandidateStatus.DISMISSED, operation_id=11
    )

    assert record.status == MergeCandidateStatus.DISMISSED.value
    assert record.reviewed_operation_id == 11
    assert record.reviewed_at is not None


def test_repository_expiration_appends_stable_reason_and_is_terminal(session: Session) -> None:
    repository = EventMergeCandidateRepository(session)
    candidate_id = repository.upsert_candidate(draft(), 10).id
    session.flush()

    record = repository.mark_expired(candidate_id, "event_merge_version_changed")

    assert record.status == MergeCandidateStatus.EXPIRED.value
    assert record.reason_codes[-1] == "event_merge_version_changed"
    with pytest.raises(ValueError, match="event_merge_invalid_transition"):
        repository.mark_reviewed(candidate_id, MergeCandidateStatus.CONFIRMED, 11)


def test_repository_rejects_review_to_non_review_status(session: Session) -> None:
    repository = EventMergeCandidateRepository(session)
    candidate_id = repository.upsert_candidate(draft(), 10).id
    session.flush()

    with pytest.raises(ValueError, match="event_merge_invalid_transition"):
        repository.mark_reviewed(candidate_id, MergeCandidateStatus.APPLIED, 11)


def test_repository_missing_candidate_raises_lookup_error(session: Session) -> None:
    repository = EventMergeCandidateRepository(session)

    assert repository.get(999) is None
    with pytest.raises(LookupError, match="event_merge_candidate_not_found"):
        repository.mark_expired(999, "event_merge_version_changed")
