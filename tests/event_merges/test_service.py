from collections import Counter
from collections.abc import Iterator
from datetime import UTC, date, datetime
from json import dumps
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import newsradar.event_merges.service as merge_service_module
from newsradar.db.models import (
    Base,
    DailyReportItemRecord,
    DailyReportRecord,
    EventCandidateRecord,
    EventItemRecord,
    EventMergeCandidateRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    OperationRunRecord,
    RawItemProcessingRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.event_merges.facts import load_event_facts
from newsradar.event_merges.repository import EventMergeCandidateRepository
from newsradar.event_merges.rules import classify_pair
from newsradar.event_merges.schema import EventMergeFacts, MergeCandidateType
from newsradar.event_merges.service import (
    EventMergeLeaseUnavailable,
    EventMergeService,
    _iter_bounded_event_pairs,
    candidate_still_safe,
)
from newsradar.events.operation_snapshots import EventVersionRef
from newsradar.events.repository import EventRepository
from newsradar.operations.deadlines import OperationTimedOut
from newsradar.operations.worker import OperationCancelled

NOW = datetime(2026, 7, 16, 4, tzinfo=UTC)


def _pair_facts(event_id: int) -> EventMergeFacts:
    return EventMergeFacts(
        event_id=event_id,
        version_number=1,
        visibility="current",
        canonical_key=f"event-{event_id}",
        algorithm_versions=("cluster-v3",),
        raw_item_ids=(10,),
        source_ids=(f"source-{event_id}",),
        publishers=(),
        published_at=(NOW,),
        safe_url_identities=(),
        strong_identities=(),
        object_entities=("model:orion",),
        actions=("launch",),
        evidence_roots=(),
    )


def test_candidate_still_safe_requires_the_original_candidate_type() -> None:
    left = _pair_facts(1).model_copy(update={"strong_identities": ("publisher.test/story",)})
    right = _pair_facts(2).model_copy(update={"strong_identities": ("publisher.test/story",)})

    assert candidate_still_safe(
        MergeCandidateType.DETERMINISTIC_MERGE,
        left,
        right,
        latest_snapshot_event_ids=frozenset(),
    )
    assert not candidate_still_safe(
        MergeCandidateType.MANUAL_REVIEW,
        left,
        right,
        latest_snapshot_event_ids=frozenset(),
    )


def test_legacy_identity_revalidation_requires_exact_cross_algorithm_membership() -> None:
    legacy = _pair_facts(3).model_copy(update={"algorithm_versions": ("cluster-v2",)})
    current = _pair_facts(9)

    assert candidate_still_safe(
        MergeCandidateType.LEGACY_IDENTITY,
        legacy,
        current,
        latest_snapshot_event_ids=frozenset({9}),
    )
    assert not candidate_still_safe(
        MergeCandidateType.LEGACY_IDENTITY,
        legacy,
        current,
        latest_snapshot_event_ids=frozenset(),
    )
    assert not candidate_still_safe(
        MergeCandidateType.LEGACY_IDENTITY,
        legacy,
        current,
        latest_snapshot_event_ids=frozenset({3}),
    )
    assert not candidate_still_safe(
        MergeCandidateType.LEGACY_IDENTITY,
        legacy.model_copy(update={"visibility": "legacy"}),
        current,
        latest_snapshot_event_ids=frozenset({3, 9}),
    )
    assert not candidate_still_safe(
        MergeCandidateType.LEGACY_IDENTITY,
        legacy.model_copy(update={"raw_item_ids": (11,)}),
        current,
        latest_snapshot_event_ids=frozenset({3, 9}),
    )


def test_survivor_selection_uses_snapshot_then_algorithm_then_lower_id() -> None:
    legacy = _pair_facts(3).model_copy(update={"algorithm_versions": ("cluster-v2",)})
    current = _pair_facts(9)
    service = EventMergeService(SimpleNamespace())

    survivor, absorbed = service._select_survivor(
        SimpleNamespace(candidate_type="legacy_identity"),
        legacy,
        current,
        latest_snapshot_event_ids=frozenset({9}),
    )
    assert (survivor.event_id, absorbed.event_id) == (9, 3)

    survivor, absorbed = service._select_survivor(
        SimpleNamespace(candidate_type="deterministic_merge"),
        legacy,
        current,
        latest_snapshot_event_ids=frozenset(),
    )
    assert (survivor.event_id, absorbed.event_id) == (9, 3)

    same_algorithm = current.model_copy(update={"event_id": 2})
    survivor, absorbed = service._select_survivor(
        SimpleNamespace(candidate_type="deterministic_merge"),
        current,
        same_algorithm,
        latest_snapshot_event_ids=frozenset(),
    )
    assert (survivor.event_id, absorbed.event_id) == (2, 9)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
    engine.dispose()


def _source(source_id: str) -> SourceDefinitionRecord:
    return SourceDefinitionRecord(
        id=source_id,
        name=source_id,
        provider_id="independent",
        nature="media",
        language="en",
        roles=["evidence"],
        topics=["ai"],
        authority_score=80,
        poll_interval_minutes=60,
        expected_fields=["title"],
        definition_hash=(source_id[-1] * 64)[:64],
    )


def _seed_event(
    session: Session,
    event_id: int,
    raw_item_id: int,
    *,
    url: str,
    title: str = "OpenAI launches Orion model",
) -> None:
    source_id = f"source-{event_id}"
    session.add(_source(source_id))
    session.add(
        RawItemRecord(
            id=raw_item_id,
            source_id=source_id,
            external_id=f"item-{raw_item_id}",
            canonical_url=f"https://aggregator.example/{raw_item_id}",
            original_url=url,
            payload={},
            title=title,
            summary=title,
            published_at=NOW,
        )
    )
    session.add(
        EventRecord(
            id=event_id,
            canonical_key=f"event-{event_id}",
            visibility="current",
            status="confirmed",
            occurred_at=NOW,
            current_version_number=1,
        )
    )
    session.add_all(
        [
            EventVersionRecord(event_id=event_id, version_number=1, payload={}),
            EventItemRecord(
                event_id=event_id,
                raw_item_id=raw_item_id,
                added_version_number=1,
            ),
            EventCandidateRecord(
                candidate_key=f"event-{event_id}",
                algorithm_version="cluster-v3",
                title=title,
                state="active",
                metadata_json={},
            ),
        ]
    )


def _seed_scan_operation(session: Session, operation_id: int = 50) -> None:
    session.add(
        OperationRunRecord(
            id=operation_id,
            operation_type="event_merge_scan",
            trigger="test",
            status="running",
            requested_scope={},
            result_summary={},
        )
    )


def _seed_merge_operation(session: Session, operation_id: int = 51) -> None:
    session.add(
        OperationRunRecord(
            id=operation_id,
            operation_type="event_merge",
            trigger="test",
            status="running",
            requested_scope={},
            result_summary={},
        )
    )


def _seed_quality(session: Session, *raw_item_ids: int) -> None:
    session.add_all(
        RawItemProcessingRecord(
            raw_item_id=raw_item_id,
            stage="relevance",
            algorithm_version="relevance-v2",
            outcome="included",
            score=80,
            reason_codes=["ai_product_action"],
            details={},
        )
        for raw_item_id in raw_item_ids
    )


def _seed_candidate(
    session: Session,
    *,
    left_id: int = 1,
    right_id: int = 2,
    left_url: str = "https://publisher.test/story",
    right_url: str = "https://publisher.test/story",
) -> EventMergeCandidateRecord:
    _seed_event(session, left_id, 11, url=left_url)
    _seed_event(session, right_id, 22, url=right_url)
    _seed_scan_operation(session)
    _seed_merge_operation(session)
    _seed_quality(session, 11, 22)
    session.commit()
    EventMergeService(session).scan(50, lambda _: None)
    candidate = session.scalar(select(EventMergeCandidateRecord))
    assert candidate is not None
    return candidate


def _seed_legacy_candidate(session: Session) -> EventMergeCandidateRecord:
    _seed_event(session, 1, 11, url="https://publisher.test/legacy-story")
    _seed_event(session, 2, 22, url="https://publisher.test/current-story")
    _seed_scan_operation(session)
    _seed_merge_operation(session)
    _seed_quality(session, 11)
    legacy_cluster = session.scalar(
        select(EventCandidateRecord).where(EventCandidateRecord.candidate_key == "event-1")
    )
    current_membership = session.scalar(
        select(EventItemRecord).where(
            EventItemRecord.event_id == 2,
            EventItemRecord.raw_item_id == 22,
        )
    )
    assert legacy_cluster is not None
    assert current_membership is not None
    legacy_cluster.algorithm_version = "cluster-v2"
    session.delete(current_membership)
    session.add(EventItemRecord(event_id=2, raw_item_id=11, added_version_number=1))
    session.commit()
    draft = classify_pair(
        load_event_facts(session, 1),
        load_event_facts(session, 2),
        frozenset({2}),
    )
    assert draft is not None
    assert draft.candidate_type is MergeCandidateType.LEGACY_IDENTITY
    candidate = EventMergeCandidateRepository(session).upsert_candidate(draft, 50)
    session.commit()
    return candidate


def test_apply_uses_one_frozen_latest_snapshot_for_validation_and_survivor(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _seed_legacy_candidate(session)
    snapshots = (
        SimpleNamespace(event_versions=(EventVersionRef(2, 1),)),
        SimpleNamespace(event_versions=(EventVersionRef(1, 1),)),
    )
    calls = 0

    def changing_snapshot(_session):
        nonlocal calls
        snapshot = snapshots[min(calls, len(snapshots) - 1)]
        calls += 1
        return snapshot

    monkeypatch.setattr(
        "newsradar.event_merges.service.latest_complete_event_snapshot",
        changing_snapshot,
    )

    result = EventMergeService(session).apply(candidate.id, 51, lambda _: None)

    assert result.status == "succeeded"
    assert result.survivor_event_id == 2
    assert result.legacy_event_id == 1
    assert calls == 1


def _rows(session: Session, model) -> list[tuple]:
    columns = tuple(model.__table__.columns)
    return list(session.execute(select(*columns).order_by(columns[0])).all())


def test_scan_writes_candidates_without_changing_event_or_source_state(session: Session) -> None:
    shared = "https://www.reuters.com/technology/orion-1?utm_source=feed"
    _seed_event(session, 1, 11, url=shared)
    _seed_event(session, 2, 22, url=shared)
    _seed_event(
        session,
        3,
        33,
        url="https://example.net/unrelated",
        title="Microsoft acquires Atlas project",
    )
    _seed_scan_operation(session)
    session.commit()
    protected = (
        EventRecord,
        EventVersionRecord,
        EventItemRecord,
        RawItemRecord,
        SourceDefinitionRecord,
    )
    before = {model: _rows(session, model) for model in protected}
    checkpoints: list[str] = []

    result = EventMergeService(session).scan(50, checkpoints.append)

    assert result.candidate_type_counts == {"manual_review": 1}
    assert result.current_event_count == 3
    assert result.single_member_event_count == 3
    assert session.query(EventMergeCandidateRecord).count() == 1
    assert {model: _rows(session, model) for model in protected} == before
    assert checkpoints


def test_apply_recomputes_survivor_and_retires_absorbed_event(session: Session) -> None:
    candidate = _seed_candidate(session)

    result = EventMergeService(session).apply(candidate.id, 51, lambda _: None)

    assert result.status == "succeeded"
    assert result.survivor_event_id == 1
    assert result.survivor_version_number == 2
    assert result.legacy_event_id == 2
    assert result.legacy_version_number == 2
    survivor = session.get(EventRecord, 1)
    legacy = session.get(EventRecord, 2)
    assert survivor is not None and survivor.visibility == "current"
    assert legacy is not None and legacy.visibility == "legacy"
    assert legacy.status == "confirmed"
    assert set(
        session.scalars(
            select(EventItemRecord.raw_item_id).where(
                EventItemRecord.event_id == 1,
                EventItemRecord.removed_version_number.is_(None),
            )
        )
    ) == {11, 22}
    assert (
        tuple(
            session.scalars(
                select(EventItemRecord.raw_item_id).where(
                    EventItemRecord.event_id == 2,
                    EventItemRecord.removed_version_number.is_(None),
                )
            )
        )
        == ()
    )
    session.refresh(candidate)
    assert candidate.status == "applied"
    assert candidate.applied_operation_id == 51
    assert candidate.result_summary == result.model_dump(mode="json")


def test_apply_expires_candidate_when_event_version_changes(session: Session) -> None:
    candidate = _seed_candidate(session)
    before_memberships = _rows(session, EventItemRecord)
    left = session.get(EventRecord, candidate.left_event_id)
    assert left is not None
    session.add(EventVersionRecord(event_id=left.id, version_number=2, payload={}))
    left.current_version_number = 2
    session.commit()

    result = EventMergeService(session).apply(candidate.id, 51, lambda _: None)

    assert result == result.expired(candidate.id, "event_merge_version_changed")
    session.refresh(candidate)
    assert candidate.status == "expired"
    assert _rows(session, EventItemRecord) == before_memberships


def test_apply_expires_pending_v1_candidate_before_any_publication(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _seed_candidate(session)
    candidate.algorithm_version = "event-merge-v1"
    session.commit()
    protected = (EventVersionRecord, EventItemRecord, EventScoreRecord)
    before = {model: _rows(session, model) for model in protected}

    def fail_publication(*_args, **_kwargs):
        pytest.fail("historical v1 candidate reached publication", pytrace=False)

    monkeypatch.setattr(
        EventMergeService,
        "_publish_revalidated_pair",
        fail_publication,
    )

    result = EventMergeService(session).apply(candidate.id, 51, lambda _: None)

    session.refresh(candidate)
    assert result == result.expired(candidate.id, "event_merge_algorithm_changed")
    assert candidate.status == "expired"
    assert {model: _rows(session, model) for model in protected} == before


def test_apply_revalidates_after_claim_when_version_changes_after_preread(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _seed_candidate(session)
    original_claim = EventRepository.claim_event
    changed = False

    def change_before_first_claim(repository, event_id, operation_id, lease_until):
        nonlocal changed
        if not changed:
            changed = True
            event = session.get(EventRecord, candidate.left_event_id)
            assert event is not None
            session.add(
                EventVersionRecord(
                    event_id=event.id,
                    version_number=2,
                    payload={"concurrent": True},
                )
            )
            event.current_version_number = 2
        return original_claim(repository, event_id, operation_id, lease_until)

    monkeypatch.setattr(EventRepository, "claim_event", change_before_first_claim)

    result = EventMergeService(session).apply(candidate.id, 51, lambda _: None)

    assert result == result.expired(candidate.id, "event_merge_version_changed")
    session.refresh(candidate)
    assert candidate.status == "expired"
    assert session.get(EventRecord, candidate.right_event_id).visibility == "current"
    assert session.get(EventRecord, candidate.right_event_id).current_version_number == 1


def test_apply_revalidates_membership_after_claim(session: Session, monkeypatch) -> None:
    candidate = _seed_candidate(session)
    original_claim = EventRepository.claim_event
    changed = False

    def change_membership_before_first_claim(repository, event_id, operation_id, lease_until):
        nonlocal changed
        if not changed:
            changed = True
            session.add(
                EventItemRecord(
                    event_id=candidate.left_event_id,
                    raw_item_id=22,
                    added_version_number=1,
                )
            )
        return original_claim(repository, event_id, operation_id, lease_until)

    monkeypatch.setattr(EventRepository, "claim_event", change_membership_before_first_claim)

    result = EventMergeService(session).apply(candidate.id, 51, lambda _: None)

    assert result == result.expired(candidate.id, "event_merge_membership_changed")
    session.refresh(candidate)
    assert candidate.status == "expired"
    assert session.get(EventRecord, candidate.right_event_id).visibility == "current"


def test_apply_expires_candidate_when_either_event_is_not_current(
    session: Session,
) -> None:
    candidate = _seed_candidate(session)
    left = session.get(EventRecord, candidate.left_event_id)
    assert left is not None
    left.visibility = "legacy"
    session.commit()
    versions_before = _rows(session, EventVersionRecord)

    result = EventMergeService(session).apply(candidate.id, 51, lambda _: None)

    assert result == result.expired(candidate.id, "event_merge_event_not_current")
    assert _rows(session, EventVersionRecord) == versions_before
    session.refresh(candidate)
    assert candidate.status == "expired"


def test_manual_candidate_requires_confirmation_before_apply(session: Session) -> None:
    candidate = _seed_candidate(
        session,
        left_url="https://publisher-a.test/story",
        right_url="https://publisher-b.test/story",
    )
    assert candidate.candidate_type == "manual_review"

    with pytest.raises(ValueError, match="event_merge_manual_confirmation_required"):
        EventMergeService(session).apply(candidate.id, 51, lambda _: None)

    reviewed = EventMergeService(session).review(candidate.id, "confirm", 51)
    assert reviewed.status == "confirmed"
    assert reviewed.reviewed_operation_id == 51
    result = EventMergeService(session).apply(candidate.id, 51, lambda _: None)
    assert result.status == "succeeded"


def test_confirm_retry_by_same_operation_continues_after_retryable_lease_failure(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _seed_candidate(
        session,
        left_url="https://publisher-a.test/story",
        right_url="https://publisher-b.test/story",
    )
    service = EventMergeService(session)
    confirmed = service.review(candidate.id, "confirm", 51)
    original_claim = EventRepository.claim_event
    attempts = 0

    def fail_once(repository, event_id, operation_id, lease_until):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return False
        return original_claim(repository, event_id, operation_id, lease_until)

    monkeypatch.setattr(EventRepository, "claim_event", fail_once)
    with pytest.raises(EventMergeLeaseUnavailable):
        service.apply(candidate.id, 51, lambda _: None)

    retried = service.review(candidate.id, "confirm", 51)
    assert retried.id == confirmed.id
    assert retried.status == "confirmed"
    result = service.apply(candidate.id, 51, lambda _: None)
    assert result.status == "succeeded"


def test_confirm_retry_by_different_operation_is_rejected(session: Session) -> None:
    candidate = _seed_candidate(
        session,
        left_url="https://publisher-a.test/story",
        right_url="https://publisher-b.test/story",
    )
    service = EventMergeService(session)
    service.review(candidate.id, "confirm", 51)

    with pytest.raises(ValueError, match="event_merge_candidate_not_reviewable"):
        service.review(candidate.id, "confirm", 52)


def test_apply_claims_events_in_sorted_order_and_releases_reverse(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = _seed_candidate(session, left_id=9, right_id=3)
    observed: list[tuple[str, int]] = []
    original_claim = EventRepository.claim_event
    original_release = EventRepository.release_event

    def claim(repository, event_id, operation_id, lease_until):
        observed.append(("claim", event_id))
        return original_claim(repository, event_id, operation_id, lease_until)

    def release(repository, event_id, operation_id):
        observed.append(("release", event_id))
        return original_release(repository, event_id, operation_id)

    monkeypatch.setattr(EventRepository, "claim_event", claim)
    monkeypatch.setattr(EventRepository, "release_event", release)

    result = EventMergeService(session).apply(candidate.id, 51, lambda _: None)

    assert result.status == "succeeded"
    assert observed == [
        ("claim", 3),
        ("claim", 9),
        ("release", 9),
        ("release", 3),
    ]


def test_apply_failure_rolls_back_both_versions_and_releases_leases(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = _seed_candidate(session)
    versions_before = _rows(session, EventVersionRecord)
    calls = 0

    def fail_second_publication(self, event, version):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("second publication failed")

    monkeypatch.setattr(
        EventRepository,
        "before_current_version_switch",
        fail_second_publication,
    )

    with pytest.raises(RuntimeError, match="second publication failed"):
        EventMergeService(session).apply(candidate.id, 51, lambda _: None)

    assert _rows(session, EventVersionRecord) == versions_before
    assert all(
        event.lease_operation_id is None and event.lease_expires_at is None
        for event in session.scalars(select(EventRecord).order_by(EventRecord.id))
    )
    session.refresh(candidate)
    assert candidate.status == "pending"


@pytest.mark.parametrize(
    "control_error",
    [OperationCancelled("cancelled"), OperationTimedOut("timed out")],
)
def test_apply_control_flow_rolls_back_and_releases_leases(
    session: Session, control_error: Exception
) -> None:
    candidate = _seed_candidate(session)

    def checkpoint(boundary: str) -> None:
        if boundary == "before_event_merge_mutation":
            raise control_error

    with pytest.raises(type(control_error)):
        EventMergeService(session).apply(candidate.id, 51, checkpoint)

    assert all(
        event.lease_operation_id is None and event.lease_expires_at is None
        for event in session.scalars(select(EventRecord).order_by(EventRecord.id))
    )
    session.refresh(candidate)
    assert candidate.status == "pending"


def test_apply_quality_input_unavailable_releases_leases(session: Session) -> None:
    candidate = _seed_candidate(session)
    session.query(RawItemProcessingRecord).delete()
    session.commit()

    with pytest.raises(ValueError, match="missing relevance"):
        EventMergeService(session).apply(candidate.id, 51, lambda _: None)

    assert all(
        event.lease_operation_id is None and event.lease_expires_at is None
        for event in session.scalars(select(EventRecord).order_by(EventRecord.id))
    )
    session.refresh(candidate)
    assert candidate.status == "pending"


def test_apply_is_idempotent_after_candidate_is_applied(session: Session) -> None:
    candidate = _seed_candidate(session)
    first = EventMergeService(session).apply(candidate.id, 51, lambda _: None)
    versions_after_first = _rows(session, EventVersionRecord)

    second = EventMergeService(session).apply(candidate.id, 51, lambda _: None)

    assert second == first
    assert _rows(session, EventVersionRecord) == versions_after_first


def test_apply_keeps_archived_daily_report_snapshot_byte_equivalent(
    session: Session,
) -> None:
    candidate = _seed_candidate(session)
    report = DailyReportRecord(
        report_date=date(2026, 7, 16),
        timezone="Asia/Shanghai",
        window_hours=24,
        window_start=NOW,
        window_end=NOW,
        source_operation_id=50,
        status="archived",
        revision=1,
        generation_summary={"event_count": 1},
        generated_at=NOW,
        archived_at=NOW,
    )
    session.add(report)
    session.flush()
    item = DailyReportItemRecord(
        daily_report_id=report.id,
        event_id=1,
        event_version_number=1,
        section="confirmed",
        position=1,
        snapshot={"event_id": 1, "version_number": 1, "zh_title": "归档事件"},
    )
    session.add(item)
    session.commit()
    before_snapshot = dumps(
        item.snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    original_version = session.scalar(
        select(EventVersionRecord).where(
            EventVersionRecord.event_id == 1,
            EventVersionRecord.version_number == 1,
        )
    )
    assert original_version is not None
    before_version = dumps(
        original_version.payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    EventMergeService(session).apply(candidate.id, 51, lambda _: None)
    session.expire_all()
    persisted_item = session.get(DailyReportItemRecord, item.id)
    persisted_version = session.get(EventVersionRecord, original_version.id)

    assert persisted_item is not None
    assert persisted_version is not None
    assert (
        dumps(
            persisted_item.snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        == before_snapshot
    )
    assert (
        dumps(
            persisted_version.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        == before_version
    )


def test_dismissed_candidate_cannot_be_applied(session: Session) -> None:
    candidate = _seed_candidate(session)
    reviewed = EventMergeService(session).review(candidate.id, "dismiss", 51)
    assert reviewed.status == "dismissed"

    with pytest.raises(ValueError, match="event_merge_candidate_not_applicable"):
        EventMergeService(session).apply(candidate.id, 51, lambda _: None)


def test_raw_item_lock_statement_uses_stable_order_for_postgresql() -> None:
    statement = EventRepository._raw_item_lock_statement((22, 11))

    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "ORDER BY raw_items.id" in compiled
    assert compiled.endswith("FOR UPDATE")


def test_apply_locks_all_raw_members_and_never_rereads_them_for_publication(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _seed_candidate(session)
    locked_ids: list[tuple[int, ...]] = []
    original_lock = EventRepository.lock_raw_items

    def capture_lock(
        repository: EventRepository, raw_item_ids: tuple[int, ...]
    ) -> tuple[RawItemRecord, ...]:
        locked_ids.append(raw_item_ids)
        return original_lock(repository, raw_item_ids)

    def fail_reread(*_args, **_kwargs):
        pytest.fail("publication reread mutable RawItem rows", pytrace=False)

    monkeypatch.setattr(EventRepository, "lock_raw_items", capture_lock)
    monkeypatch.setattr(
        merge_service_module,
        "_event_cluster_items",
        fail_reread,
        raising=False,
    )

    result = EventMergeService(session).apply(candidate.id, 51, lambda _: None)

    assert result.status == "succeeded"
    assert locked_ids == [(11, 22)]


def test_apply_builds_facts_and_cluster_items_from_same_locked_rows(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _seed_candidate(session)
    fact_row_objects: dict[int, tuple[int, ...]] = {}
    cluster_row_objects: tuple[int, ...] = ()
    original_facts = merge_service_module.build_event_facts_from_rows
    original_items = merge_service_module._cluster_items_from_rows

    def capture_facts(session, event, rows):
        fact_row_objects[event.id] = tuple(id(raw) for raw, _source in rows)
        return original_facts(session, event, rows)

    def capture_items(rows):
        nonlocal cluster_row_objects
        cluster_row_objects = tuple(id(raw) for raw, _source in rows)
        return original_items(rows)

    monkeypatch.setattr(
        merge_service_module,
        "build_event_facts_from_rows",
        capture_facts,
    )
    monkeypatch.setattr(
        merge_service_module,
        "_cluster_items_from_rows",
        capture_items,
    )

    result = EventMergeService(session).apply(candidate.id, 51, lambda _: None)

    assert result.status == "succeeded"
    assert cluster_row_objects == tuple(
        row_object
        for event_id in sorted(fact_row_objects)
        for row_object in fact_row_objects[event_id]
    )


def test_confirm_rejects_non_manual_candidate(session: Session) -> None:
    candidate = _seed_candidate(session)

    with pytest.raises(ValueError, match="event_merge_confirmation_type_mismatch"):
        EventMergeService(session).review(candidate.id, "confirm", 51)


def test_apply_expires_candidate_when_fingerprint_changes(session: Session) -> None:
    candidate = _seed_candidate(session)
    raw = session.get(RawItemRecord, 11)
    assert raw is not None
    raw.summary = "OpenAI launches a different Atlas model"
    session.commit()

    result = EventMergeService(session).apply(candidate.id, 51, lambda _: None)

    assert result == result.expired(candidate.id, "event_merge_membership_changed")
    session.refresh(candidate)
    assert candidate.status == "expired"


def test_apply_releases_partial_claim_without_stealing_other_lease(
    session: Session,
) -> None:
    candidate = _seed_candidate(session)
    other_deadline = datetime.now(UTC).replace(microsecond=0)
    right = session.get(EventRecord, candidate.right_event_id)
    assert right is not None
    right.lease_operation_id = 50
    right.lease_expires_at = other_deadline.replace(year=other_deadline.year + 1)
    session.commit()

    with pytest.raises(EventMergeLeaseUnavailable):
        EventMergeService(session).apply(candidate.id, 51, lambda _: None)

    left = session.get(EventRecord, candidate.left_event_id)
    session.refresh(right)
    assert left is not None and left.lease_operation_id is None
    assert right.lease_operation_id == 50
    assert right.lease_expires_at is not None


def test_recheck_expires_old_candidate_and_only_rescans_its_pair(
    session: Session,
) -> None:
    candidate = _seed_candidate(session)
    raw = session.get(RawItemRecord, 11)
    assert raw is not None
    raw.original_url = "https://publisher.test/story-revised"
    session.commit()
    protected = (EventRecord, EventVersionRecord, EventItemRecord)
    before = {model: _rows(session, model) for model in protected}

    replacement = EventMergeService(session).review(candidate.id, "recheck", 51)

    session.refresh(candidate)
    assert candidate.status == "expired"
    assert candidate.reason_codes[-1] == "event_merge_recheck_requested"
    assert replacement.id != candidate.id
    assert replacement.status == "pending"
    assert replacement.revision == 2
    assert replacement.supersedes_candidate_id == candidate.id
    assert replacement.generated_operation_id == 51
    assert candidate.reviewed_operation_id == 51
    assert candidate.reviewed_at is not None
    assert candidate.result_summary == {
        "recheck_outcome": "revision",
        "recheck_candidate_id": replacement.id,
    }
    retried = EventMergeService(session).review(candidate.id, "recheck", 51)
    assert retried.id == replacement.id
    assert session.query(EventMergeCandidateRecord).count() == 2
    with pytest.raises(ValueError, match="event_merge_candidate_not_reviewable"):
        EventMergeService(session).review(candidate.id, "recheck", 52)
    assert {model: _rows(session, model) for model in protected} == before


def test_recheck_changed_version_creates_idempotent_new_root(
    session: Session,
) -> None:
    candidate = _seed_candidate(session)
    candidate_id = candidate.id
    left = session.get(EventRecord, candidate.left_event_id)
    assert left is not None
    session.add(
        EventVersionRecord(
            event_id=left.id,
            version_number=2,
            payload={"recheck": "new-version"},
        )
    )
    left.current_version_number = 2
    session.commit()

    replacement = EventMergeService(session).review(candidate_id, "recheck", 51)

    session.refresh(candidate)
    assert replacement.id != candidate_id
    assert replacement.left_version_number == 2
    assert replacement.revision == 1
    assert replacement.supersedes_candidate_id is None
    assert candidate.status == "expired"
    assert candidate.reviewed_operation_id == 51
    assert candidate.reviewed_at is not None
    assert candidate.result_summary == {
        "recheck_outcome": "new_root",
        "recheck_candidate_id": replacement.id,
    }
    session.expire_all()

    retried = EventMergeService(session).review(candidate_id, "recheck", 51)

    assert retried.id == replacement.id
    assert session.query(EventMergeCandidateRecord).count() == 2
    with pytest.raises(ValueError, match="event_merge_candidate_not_reviewable"):
        EventMergeService(session).review(candidate_id, "recheck", 52)


def test_recheck_without_new_candidate_is_operation_idempotent(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _seed_candidate(session)
    candidate_id = candidate.id
    monkeypatch.setattr(
        "newsradar.event_merges.service.classify_pair",
        lambda left, right, snapshot_ids: None,
    )

    expired = EventMergeService(session).review(candidate_id, "recheck", 51)

    assert expired.id == candidate_id
    assert expired.status == "expired"
    assert expired.reviewed_operation_id == 51
    assert expired.reviewed_at is not None
    assert expired.result_summary == {
        "recheck_outcome": "no_candidate",
        "recheck_candidate_id": None,
    }
    session.expire_all()

    retried = EventMergeService(session).review(candidate_id, "recheck", 51)

    assert retried.id == candidate_id
    assert session.query(EventMergeCandidateRecord).count() == 1
    with pytest.raises(ValueError, match="event_merge_candidate_not_reviewable"):
        EventMergeService(session).review(candidate_id, "recheck", 52)


def test_scan_isolates_malformed_event_and_continues(session: Session) -> None:
    shared = "https://www.reuters.com/technology/orion-1"
    _seed_event(session, 1, 11, url=shared)
    _seed_event(session, 2, 22, url=shared)
    session.add(
        EventRecord(
            id=3,
            canonical_key="malformed",
            visibility="current",
            status="confirmed",
            current_version_number=1,
        )
    )
    _seed_scan_operation(session)
    session.commit()

    result = EventMergeService(session).scan(50, lambda _: None)

    assert result.candidate_type_counts == {"deterministic_merge": 1}
    assert result.failure_reasons == {"fact_load_failed": 1}


def test_real_scan_regression_keeps_partial_overlap_manual_and_youtube_ids_separate(
    session: Session,
) -> None:
    _seed_event(
        session,
        1,
        453,
        url="https://publisher.test/shared-story",
        title="AI company publishes quarterly result",
    )
    _seed_event(
        session,
        2,
        382,
        url="https://publisher.test/second-story",
        title="Another company announces a different result",
    )
    session.add(EventItemRecord(event_id=2, raw_item_id=453, added_version_number=1))
    youtube_rows = (
        (87, 392, "-J5KoSMfPLk", "Learning with AI at Any Stage of Life | Fast Campus x OpenAI"),
        (
            119,
            637,
            "KmfxdySAtNc",
            "Tune the Harness, Before Tuning the Model with LangChain | Nemotron Labs",
        ),
        (
            132,
            666,
            "2kvu6h1FQPc",
            "Karpathy: Context Windows are a cheap way to manupilate AI",
        ),
        (
            152,
            731,
            "jhpmMTus5a0",
            "The AI Memory Problem: Why Long Context Isn’t Enough — "
            "Dan Biderman, Engram Co-founder & CEO",
        ),
        (
            282,
            697,
            "l2b9UrSsz-w",
            "Alignment with Awakening: Davidad on Moral Realism, AI Wisdom, "
            "& why His p(Doom) is Down to 5%",
        ),
    )
    for event_id, raw_item_id, video_id, title in youtube_rows:
        _seed_event(
            session,
            event_id,
            raw_item_id,
            url=f"https://www.youtube.com/watch?v={video_id}",
            title=title,
        )
    _seed_scan_operation(session)
    session.commit()

    result = EventMergeService(session).scan(50, lambda _: None)

    candidates = session.scalars(select(EventMergeCandidateRecord)).all()
    assert result.candidate_type_counts == {"manual_review": 1}
    assert len(candidates) == 1
    assert (candidates[0].left_event_id, candidates[0].right_event_id) == (1, 2)
    assert candidates[0].reason_codes == ["partial_membership_overlap"]
    assert all(candidate.candidate_type != "deterministic_merge" for candidate in candidates)


def test_scan_does_not_compare_unindexed_unrelated_events(session: Session, monkeypatch) -> None:
    for event_id in range(1, 7):
        _seed_event(
            session,
            event_id,
            event_id * 10,
            url=f"https://example.com/story/{event_id}",
            title=f"Unique headline {event_id}",
        )
    _seed_scan_operation(session)
    session.commit()
    compared: list[tuple[int, int]] = []

    def record_pair(left, right, latest_snapshot_event_ids):
        compared.append((left.event_id, right.event_id))
        return None

    monkeypatch.setattr("newsradar.event_merges.service.classify_pair", record_pair)

    EventMergeService(session).scan(50, lambda _: None)

    assert compared == []


@pytest.mark.parametrize(
    "url",
    [
        "https://publisher.test/",
        "https://publisher.test/news",
        "https://publisher.test/feed",
        "https://publisher.test/category/ai",
        "https://publisher.test/news/page/2",
        "https://publisher.test/aggregator/latest",
    ],
)
def test_scan_never_creates_deterministic_candidate_from_collection_url(
    session: Session,
    url: str,
) -> None:
    _seed_event(session, 1, 11, url=url, title="First independent bulletin")
    _seed_event(session, 2, 22, url=url, title="Second unrelated analysis")
    _seed_scan_operation(session)
    session.commit()

    result = EventMergeService(session).scan(50, lambda _: None)

    assert result.candidate_type_counts.get("deterministic_merge", 0) == 0
    assert all(
        candidate.candidate_type != "deterministic_merge"
        for candidate in session.scalars(select(EventMergeCandidateRecord))
    )


def test_scan_expires_pending_candidate_when_referenced_version_is_stale(
    session: Session,
) -> None:
    shared = "https://www.reuters.com/technology/orion-1"
    _seed_event(session, 1, 11, url=shared)
    _seed_event(session, 2, 22, url=shared)
    _seed_scan_operation(session, 50)
    session.commit()
    EventMergeService(session).scan(50, lambda _: None)
    stale = session.scalar(select(EventMergeCandidateRecord))
    assert stale is not None

    session.get(OperationRunRecord, 50).status = "succeeded"
    session.add(EventVersionRecord(event_id=1, version_number=2, payload={}))
    session.get(EventRecord, 1).current_version_number = 2
    _seed_scan_operation(session, 51)
    session.commit()

    result = EventMergeService(session).scan(51, lambda _: None)

    session.refresh(stale)
    assert stale.status == "expired"
    assert "referenced_version_no_longer_current" in stale.reason_codes
    assert result.status_counts == {"expired": 1, "pending": 1}


def test_scan_isolates_one_candidate_integrity_failure(session: Session, monkeypatch) -> None:
    shared = "https://www.reuters.com/technology/orion-1"
    for event_id in (1, 2, 3):
        _seed_event(session, event_id, event_id * 10, url=shared)
    _seed_scan_operation(session)
    session.commit()
    original = EventMergeCandidateRepository.upsert_candidate
    attempts = 0

    def fail_first(self, draft, generated_operation_id):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise IntegrityError("candidate", {}, Exception("bounded failure"))
        return original(self, draft, generated_operation_id)

    monkeypatch.setattr(EventMergeCandidateRepository, "upsert_candidate", fail_first)

    result = EventMergeService(session).scan(50, lambda _: None)

    assert attempts == 3
    assert session.query(EventMergeCandidateRecord).count() == 2
    assert result.failure_reasons == {"candidate_integrity_failed": 1}


def test_pair_stream_checkpoints_before_materializing_dense_bucket() -> None:
    checkpoints: list[str] = []
    failures: Counter[str] = Counter()
    stream = _iter_bounded_event_pairs(
        tuple(_pair_facts(event_id) for event_id in range(1, 20)),
        checkpoints.append,
        failures,
        max_bucket_fanout=100,
        max_pairs=100,
    )

    first = next(stream)

    assert first == (1, 2)
    assert checkpoints[0].startswith("event_merge_pair_bucket:")


def test_pair_stream_enforces_bucket_fanout_and_total_pair_budget() -> None:
    fanout_failures: Counter[str] = Counter()
    fanout_pairs = tuple(
        _iter_bounded_event_pairs(
            tuple(_pair_facts(event_id) for event_id in range(1, 8)),
            lambda _: None,
            fanout_failures,
            max_bucket_fanout=4,
            max_pairs=2,
        )
    )
    budget_failures: Counter[str] = Counter()
    budget_pairs = tuple(
        _iter_bounded_event_pairs(
            tuple(_pair_facts(event_id) for event_id in range(1, 8)),
            lambda _: None,
            budget_failures,
            max_bucket_fanout=10,
            max_pairs=2,
        )
    )

    assert fanout_pairs == ()
    assert fanout_failures["pair_bucket_fanout_exceeded"] >= 1
    assert len(budget_pairs) == 2
    assert budget_failures == {"pair_budget_exhausted": 1}


def test_pair_stream_propagates_checkpoint_cancellation_identity() -> None:
    cancellation = OperationCancelled("cancel-now")

    def cancel(_boundary: str) -> None:
        raise cancellation

    stream = _iter_bounded_event_pairs(
        tuple(_pair_facts(event_id) for event_id in range(1, 20)),
        cancel,
        Counter(),
        max_bucket_fanout=100,
        max_pairs=100,
    )

    with pytest.raises(OperationCancelled) as caught:
        next(stream)

    assert caught.value is cancellation


def test_pair_stream_checkpoints_within_dense_bucket() -> None:
    cancellation = OperationCancelled("cancel-dense-bucket")

    def cancel_on_progress(boundary: str) -> None:
        if boundary.startswith("event_merge_pair_bucket_progress:"):
            raise cancellation

    stream = _iter_bounded_event_pairs(
        tuple(_pair_facts(event_id) for event_id in range(1, 20)),
        cancel_on_progress,
        Counter(),
        max_bucket_fanout=100,
        max_pairs=1_000,
    )

    with pytest.raises(OperationCancelled) as caught:
        tuple(stream)

    assert caught.value is cancellation


def test_scan_redacts_untrusted_evidence_roots_before_candidate_snapshot(
    session: Session,
) -> None:
    shared = "https://www.reuters.com/technology/orion-1"
    _seed_event(session, 1, 11, url=shared)
    _seed_event(session, 2, 22, url=shared)
    malicious_evidence = [
        {"root_evidence_key": ("https://user:password@example.com/story?token=secret#private")},
        {"root_evidence_key": "publisher:reuters"},
        {"root_evidence_key": "authorization:Bearer-secret"},
        {"root_evidence_key": "user:pass@example.com/private"},
        {"root_evidence_key": "unsafe\x00control"},
    ]
    for version in session.scalars(select(EventVersionRecord)):
        version.payload = {"evidence": malicious_evidence}
    _seed_scan_operation(session)
    session.commit()

    result = EventMergeService(session).scan(50, lambda _: None)
    record = session.scalar(select(EventMergeCandidateRecord))

    assert result.candidate_type_counts == {"deterministic_merge": 1}
    assert record is not None
    serialized = repr(record.facts_snapshot)
    assert "example.com/story" not in serialized
    assert "publisher:reuters" in serialized
    assert "secret" not in serialized.casefold()
    assert "password" not in serialized.casefold()
    assert "authorization" not in serialized.casefold()
    assert "user:pass" not in serialized.casefold()
    assert "\x00" not in serialized
