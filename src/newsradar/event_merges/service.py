"""Read-only event scanning with isolated candidate/audit writes."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newsradar.db.models import EventMergeCandidateRecord, EventRecord
from newsradar.event_merges.facts import (
    EVENT_MERGE_RULE_VERSION,
    load_event_facts,
    merge_input_fingerprint,
)
from newsradar.event_merges.repository import EventMergeCandidateRepository
from newsradar.event_merges.rules import classify_pair
from newsradar.event_merges.schema import (
    EventMergeFacts,
    MergeApplyResult,
    MergeCandidateStatus,
    MergeCandidateType,
)
from newsradar.events.operation_snapshots import latest_complete_event_snapshot
from newsradar.events.pipeline import build_candidate_score_input, load_operation_window_end
from newsradar.events.publishing import EventPublisher
from newsradar.events.repository import EventRepository
from newsradar.events.runtime import _enrichment, _event_cluster_items, _snapshot
from newsradar.events.schema import CandidateCluster, EventCategory, EventVisibility

_TIME_BUCKET_SECONDS = 48 * 60 * 60
MAX_PAIR_BUCKET_FANOUT = 500
MAX_SCAN_PAIRS = 10_000
_PAIR_CHECKPOINT_INTERVAL = 100


class EventMergeLeaseUnavailable(RuntimeError):
    error_code = "event_merge_lease_unavailable"

    def __init__(self, event_id: int) -> None:
        super().__init__(f"Event {event_id} is being changed by another worker")
        self.event_id = event_id


def candidate_still_safe(
    candidate_type: MergeCandidateType | str,
    left: EventMergeFacts,
    right: EventMergeFacts,
    *,
    latest_snapshot_event_ids: frozenset[int],
) -> bool:
    if left.visibility != "current" or right.visibility != "current":
        return False
    expected = MergeCandidateType(candidate_type)
    current = classify_pair(
        left,
        right,
        latest_snapshot_event_ids,
    )
    return current is not None and current.candidate_type is expected


@dataclass(frozen=True, slots=True)
class MergeScanResult:
    candidate_type_counts: dict[str, int] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)
    failure_reasons: dict[str, int] = field(default_factory=dict)
    current_event_count: int = 0
    single_member_event_count: int = 0
    cross_source_event_count: int = 0
    overlapping_current_membership_count: int = 0
    pair_count: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_type_counts": dict(self.candidate_type_counts),
            "status_counts": dict(self.status_counts),
            "failure_reasons": dict(self.failure_reasons),
            "current_event_count": self.current_event_count,
            "single_member_event_count": self.single_member_event_count,
            "cross_source_event_count": self.cross_source_event_count,
            "overlapping_current_membership_count": (
                self.overlapping_current_membership_count
            ),
            "pair_count": self.pair_count,
        }


class EventMergeService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def review(
        self,
        candidate_id: int,
        decision: str,
        operation_id: int,
    ) -> EventMergeCandidateRecord:
        repository = EventMergeCandidateRepository(self.session)
        record = repository.get(candidate_id, for_update=True)
        if record is None:
            raise LookupError("event_merge_candidate_not_found")
        if (
            decision == "confirm"
            and record.status
            in {
                MergeCandidateStatus.CONFIRMED.value,
                MergeCandidateStatus.APPLIED.value,
            }
            and record.reviewed_operation_id == operation_id
        ):
            self.session.commit()
            return record
        if decision == "recheck":
            existing = repository.child_of(candidate_id, for_update=True)
            if existing is not None:
                self.session.commit()
                return existing
        if record.status != MergeCandidateStatus.PENDING.value:
            raise ValueError("event_merge_candidate_not_reviewable")
        if decision == "confirm":
            if record.candidate_type != MergeCandidateType.MANUAL_REVIEW.value:
                raise ValueError("event_merge_confirmation_type_mismatch")
            reviewed = repository.mark_reviewed(
                candidate_id,
                MergeCandidateStatus.CONFIRMED,
                operation_id,
            )
        elif decision == "dismiss":
            reviewed = repository.mark_reviewed(
                candidate_id,
                MergeCandidateStatus.DISMISSED,
                operation_id,
            )
        elif decision == "recheck":
            left = load_event_facts(self.session, record.left_event_id)
            right = load_event_facts(self.session, record.right_event_id)
            latest = latest_complete_event_snapshot(self.session)
            latest_ids = (
                frozenset(reference.event_id for reference in latest.event_versions)
                if latest is not None
                else frozenset()
            )
            draft = classify_pair(left, right, latest_ids)
            reviewed = (
                repository.create_revision(
                    candidate_id,
                    draft,
                    generated_operation_id=operation_id,
                    reason_code="event_merge_recheck_requested",
                )
                if draft is not None
                else repository.mark_expired(
                    candidate_id, "event_merge_recheck_requested"
                )
            )
        else:
            raise ValueError("event_merge_invalid_review_decision")
        self.session.commit()
        return reviewed

    def apply(
        self,
        candidate_id: int,
        operation_id: int,
        checkpoint: Callable[[str], None],
    ) -> MergeApplyResult:
        repository = EventMergeCandidateRepository(self.session)
        record = repository.get(candidate_id)
        if record is None:
            raise LookupError("event_merge_candidate_not_found")
        if record.status == MergeCandidateStatus.APPLIED.value:
            return MergeApplyResult.model_validate(record.result_summary)
        event_ids = tuple(sorted((record.left_event_id, record.right_event_id)))
        claimed_ids: list[int] = []
        try:
            event_repository = EventRepository(self.session)
            lease_until = datetime.now(UTC) + timedelta(minutes=5)
            for event_id in event_ids:
                if not event_repository.claim_event(
                    event_id, operation_id, lease_until
                ):
                    raise EventMergeLeaseUnavailable(event_id)
                claimed_ids.append(event_id)
            self.session.commit()
            checkpoint("before_event_merge_mutation")
            with self.session.begin():
                repository = EventMergeCandidateRepository(self.session)
                locked_record = repository.get(candidate_id, for_update=True)
                if locked_record is None:
                    raise LookupError("event_merge_candidate_not_found")
                locked_events = EventRepository(self.session).lock_events(event_ids)
                if tuple(event.id for event in locked_events) != event_ids:
                    raise LookupError("event_merge_event_not_found")
                if locked_record.status == MergeCandidateStatus.APPLIED.value:
                    result = MergeApplyResult.model_validate(
                        locked_record.result_summary
                    )
                else:
                    current_left = load_event_facts(
                        self.session, locked_record.left_event_id
                    )
                    current_right = load_event_facts(
                        self.session, locked_record.right_event_id
                    )
                    snapshot = latest_complete_event_snapshot(self.session)
                    latest_snapshot_ids = (
                        frozenset(
                            reference.event_id
                            for reference in snapshot.event_versions
                        )
                        if snapshot is not None
                        else frozenset()
                    )
                    error_code = self._locked_revalidation_error(
                        locked_record,
                        current_left,
                        current_right,
                        operation_id=operation_id,
                        latest_snapshot_event_ids=latest_snapshot_ids,
                    )
                    if error_code is not None:
                        repository.mark_expired(candidate_id, error_code)
                        result = MergeApplyResult.expired(candidate_id, error_code)
                    else:
                        with self.session.begin_nested():
                            result = self._publish_revalidated_pair(
                                record=locked_record,
                                left=current_left,
                                right=current_right,
                                operation_id=operation_id,
                                latest_snapshot_event_ids=latest_snapshot_ids,
                            )
                            checkpoint("after_event_merge_mutation")
                            repository.mark_applied(
                                candidate_id,
                                operation_id,
                                result.model_dump(mode="json"),
                            )
                for event_id in reversed(claimed_ids):
                    EventRepository(self.session).release_event(
                        event_id, operation_id
                    )
            return result
        except Exception:
            self.session.rollback()
            with self.session.begin():
                for event_id in reversed(claimed_ids):
                    EventRepository(self.session).release_event(
                        event_id, operation_id
                    )
            raise

    @staticmethod
    def _locked_revalidation_error(
        record: EventMergeCandidateRecord,
        left: EventMergeFacts,
        right: EventMergeFacts,
        *,
        operation_id: int,
        latest_snapshot_event_ids: frozenset[int],
    ) -> str | None:
        if record.status not in {
            MergeCandidateStatus.CONFIRMED.value,
            MergeCandidateStatus.PENDING.value,
        }:
            raise ValueError("event_merge_candidate_not_applicable")
        if record.status == MergeCandidateStatus.PENDING.value:
            if record.candidate_type == MergeCandidateType.MANUAL_REVIEW.value:
                raise ValueError("event_merge_manual_confirmation_required")
            if record.candidate_type not in {
                MergeCandidateType.LEGACY_IDENTITY.value,
                MergeCandidateType.DETERMINISTIC_MERGE.value,
            }:
                raise ValueError(
                    "event_merge_candidate_type_not_directly_applicable"
                )
        elif record.candidate_type != MergeCandidateType.MANUAL_REVIEW.value:
            raise ValueError("event_merge_confirmation_type_mismatch")
        elif record.reviewed_operation_id != operation_id:
            raise ValueError("event_merge_confirmation_operation_mismatch")
        if record.algorithm_version != EVENT_MERGE_RULE_VERSION:
            return "event_merge_algorithm_changed"
        if left.visibility != "current" or right.visibility != "current":
            return "event_merge_event_not_current"
        if (
            left.version_number != record.left_version_number
            or right.version_number != record.right_version_number
        ):
            return "event_merge_version_changed"
        try:
            frozen_left = EventMergeFacts.model_validate(
                record.facts_snapshot["left"]
            )
            frozen_right = EventMergeFacts.model_validate(
                record.facts_snapshot["right"]
            )
        except (KeyError, TypeError, ValueError):
            return "event_merge_membership_changed"
        if (
            left.raw_item_ids != frozen_left.raw_item_ids
            or right.raw_item_ids != frozen_right.raw_item_ids
        ):
            return "event_merge_membership_changed"
        if merge_input_fingerprint(left, right) != record.input_fingerprint:
            return "event_merge_membership_changed"
        if not candidate_still_safe(
            record.candidate_type,
            left,
            right,
            latest_snapshot_event_ids=latest_snapshot_event_ids,
        ):
            return "event_merge_identity_not_strong"
        return None

    def _publish_revalidated_pair(
        self,
        *,
        record: EventMergeCandidateRecord,
        left: EventMergeFacts,
        right: EventMergeFacts,
        operation_id: int,
        latest_snapshot_event_ids: frozenset[int],
    ) -> MergeApplyResult:
        survivor_facts, legacy_facts = self._select_survivor(
            record,
            left,
            right,
            latest_snapshot_event_ids=latest_snapshot_event_ids,
        )
        survivor = self.session.get(EventRecord, survivor_facts.event_id)
        legacy = self.session.get(EventRecord, legacy_facts.event_id)
        if survivor is None or legacy is None:
            raise LookupError("event_merge_event_not_found")
        items_by_id = {
            item.raw_item_id: item
            for event_id in (left.event_id, right.event_id)
            for item in _event_cluster_items(self.session, event_id)
        }
        items = tuple(items_by_id[item_id] for item_id in sorted(items_by_id))
        current = EventRepository(self.session).get_current_event(survivor.id)
        title = (
            current.zh_title
            if current is not None and current.zh_title
            else next((item.title for item in items if item.title), survivor.canonical_key)
        )
        occurred_at = min(
            (item.published_at for item in items if item.published_at is not None),
            default=survivor.occurred_at,
        )
        candidate = CandidateCluster(
            candidate_key=survivor.canonical_key,
            title=title,
            category=EventCategory(survivor.category) if survivor.category else None,
            items=items,
            raw_item_ids=tuple(sorted(items_by_id)),
            reasons=("event_merge_revalidated",),
            occurred_at=occurred_at,
        )
        snapshot_at = load_operation_window_end(
            self.session,
            operation_id,
        )
        score_input = build_candidate_score_input(
            self.session,
            candidate,
            now=snapshot_at,
            prior_event=survivor,
        )
        try:
            safe_enrichment = _enrichment(EventRepository(self.session), survivor)
        except (TypeError, ValueError):
            safe_enrichment = None
        published = EventPublisher(EventRepository(self.session)).assemble_snapshot(
            candidate,
            score_input=score_input,
            enrichment=safe_enrichment,
            snapshot_at=snapshot_at,
        ).model_copy(
            update={
                "event_id": survivor.id,
                "canonical_key": survivor.canonical_key,
            }
        )
        survivor_record = EventRepository(self.session).publish_complete_event(
            published,
            operation_id,
        )
        legacy_record = EventRepository(self.session).publish_complete_event(
            _snapshot(
                EventRepository(self.session),
                legacy,
                source_item_ids=(),
            ),
            operation_id,
            visibility=EventVisibility.LEGACY,
        )
        return MergeApplyResult(
            status="succeeded",
            candidate_id=record.id,
            survivor_event_id=survivor_record.id,
            survivor_version_number=survivor_record.current_version_number,
            legacy_event_id=legacy_record.id,
            legacy_version_number=legacy_record.current_version_number,
        )

    def _select_survivor(
        self,
        record: EventMergeCandidateRecord,
        left: EventMergeFacts,
        right: EventMergeFacts,
        *,
        latest_snapshot_event_ids: frozenset[int],
    ) -> tuple[EventMergeFacts, EventMergeFacts]:
        if record.candidate_type == MergeCandidateType.LEGACY_IDENTITY.value:
            if (left.event_id in latest_snapshot_event_ids) != (
                right.event_id in latest_snapshot_event_ids
            ):
                survivor = (
                    left if left.event_id in latest_snapshot_event_ids else right
                )
                return survivor, right if survivor is left else left
        current_cluster = "cluster-v3"
        if (current_cluster in left.algorithm_versions) != (
            current_cluster in right.algorithm_versions
        ):
            survivor = (
                left if current_cluster in left.algorithm_versions else right
            )
            return survivor, right if survivor is left else left
        survivor = min((left, right), key=lambda facts: facts.event_id)
        return survivor, right if survivor is left else left

    def scan(
        self,
        operation_id: int,
        checkpoint: Callable[[str], None],
    ) -> MergeScanResult:
        event_ids = tuple(
            self.session.scalars(
                select(EventRecord.id)
                .where(EventRecord.visibility == "current")
                .order_by(EventRecord.id)
            )
        )
        snapshot = latest_complete_event_snapshot(self.session)
        latest_snapshot_event_ids = frozenset(
            ref.event_id for ref in snapshot.event_versions
        ) if snapshot else frozenset()
        self.session.commit()

        failures: Counter[str] = Counter()
        facts_by_id: dict[int, EventMergeFacts] = {}
        for event_id in event_ids:
            checkpoint(f"event_merge_facts:{event_id}")
            try:
                facts_by_id[event_id] = load_event_facts(self.session, event_id)
            except Exception:
                self.session.rollback()
                failures["fact_load_failed"] += 1
            else:
                self.session.commit()

        facts_values = tuple(facts_by_id.values())
        overlapping_memberships = _overlapping_current_memberships(facts_values)
        candidate_types: Counter[str] = Counter()
        pair_count = 0
        for left_id, right_id in _iter_bounded_event_pairs(
            facts_values, checkpoint, failures
        ):
            pair_count += 1
            checkpoint(f"event_merge_pair:{left_id}:{right_id}")
            left = facts_by_id[left_id]
            right = facts_by_id[right_id]
            try:
                draft = classify_pair(left, right, latest_snapshot_event_ids)
            except Exception:
                failures["pair_classification_failed"] += 1
                continue
            if draft is None:
                continue
            try:
                with self.session.begin_nested():
                    EventMergeCandidateRepository(self.session).upsert_candidate(
                        draft, operation_id
                    )
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
                failures["candidate_integrity_failed"] += 1
                continue
            except Exception:
                self.session.rollback()
                failures["candidate_write_failed"] += 1
                continue
            candidate_types[draft.candidate_type.value] += 1

        self._expire_stale_candidates(failures, checkpoint)
        status_counts = Counter(
            self.session.scalars(
                select(EventMergeCandidateRecord.status).where(
                    EventMergeCandidateRecord.algorithm_version
                    == EVENT_MERGE_RULE_VERSION
                )
            )
        )
        self.session.commit()
        return MergeScanResult(
            candidate_type_counts=dict(sorted(candidate_types.items())),
            status_counts=dict(sorted(status_counts.items())),
            failure_reasons=dict(sorted(failures.items())),
            current_event_count=len(event_ids),
            single_member_event_count=sum(
                len(facts.raw_item_ids) == 1 for facts in facts_values
            ),
            cross_source_event_count=sum(
                len(facts.source_ids) > 1 for facts in facts_values
            ),
            overlapping_current_membership_count=overlapping_memberships,
            pair_count=pair_count,
        )

    def _expire_stale_candidates(
        self,
        failures: Counter[str],
        checkpoint: Callable[[str], None],
    ) -> None:
        current_versions = dict(
            self.session.execute(
                select(EventRecord.id, EventRecord.current_version_number)
            ).all()
        )
        pending = tuple(
            self.session.scalars(
                select(EventMergeCandidateRecord).where(
                    EventMergeCandidateRecord.algorithm_version
                    == EVENT_MERGE_RULE_VERSION,
                    EventMergeCandidateRecord.status == "pending",
                )
            )
        )
        self.session.commit()
        for record in pending:
            if (
                current_versions.get(record.left_event_id) == record.left_version_number
                and current_versions.get(record.right_event_id)
                == record.right_version_number
            ):
                continue
            checkpoint(f"event_merge_expire:{record.id}")
            try:
                with self.session.begin_nested():
                    EventMergeCandidateRepository(self.session).mark_expired(
                        record.id, "referenced_version_no_longer_current"
                    )
                self.session.commit()
            except Exception:
                self.session.rollback()
                failures["candidate_expiry_failed"] += 1


def _iter_bounded_event_pairs(
    facts_values: Iterable[EventMergeFacts],
    checkpoint: Callable[[str], None],
    failures: Counter[str],
    *,
    max_bucket_fanout: int = MAX_PAIR_BUCKET_FANOUT,
    max_pairs: int = MAX_SCAN_PAIRS,
) -> Iterator[tuple[int, int]]:
    facts = tuple(facts_values)
    raw_index: defaultdict[int, list[int]] = defaultdict(list)
    strong_index: defaultdict[str, list[int]] = defaultdict(list)
    object_time_index: defaultdict[tuple[str, int], list[int]] = defaultdict(list)
    for item in facts:
        for raw_item_id in item.raw_item_ids:
            raw_index[raw_item_id].append(item.event_id)
        for identity in item.strong_identities:
            strong_index[identity].append(item.event_id)
        buckets = {
            int(_aware_utc(value).timestamp()) // _TIME_BUCKET_SECONDS
            for value in item.published_at
        }
        for entity in item.object_entities:
            for bucket in buckets:
                object_time_index[(entity, bucket)].append(item.event_id)

    buckets: list[tuple[str, tuple[int, ...], tuple[int, ...] | None]] = []
    buckets.extend(
        (f"raw:{key}", tuple(sorted(set(members))), None)
        for key, members in sorted(raw_index.items())
    )
    buckets.extend(
        (f"strong:{key}", tuple(sorted(set(members))), None)
        for key, members in sorted(strong_index.items())
    )
    for (entity, bucket), members in sorted(object_time_index.items()):
        buckets.append(
            (f"object_time:{entity}:{bucket}", tuple(sorted(set(members))), None)
        )
        adjacent = object_time_index.get((entity, bucket + 1))
        if adjacent:
            buckets.append(
                (
                    f"object_time_adjacent:{entity}:{bucket}",
                    tuple(sorted(set(members))),
                    tuple(sorted(set(adjacent))),
                )
            )

    yielded: set[tuple[int, int]] = set()
    for label, left_members, right_members in buckets:
        checkpoint(f"event_merge_pair_bucket:{label}")
        bucket_members = set(left_members)
        if right_members is not None:
            bucket_members.update(right_members)
        if len(bucket_members) > max_bucket_fanout:
            failures["pair_bucket_fanout_exceeded"] += 1
            continue
        examined = 0
        for pair in _bucket_pairs(left_members, right_members):
            examined += 1
            if examined % _PAIR_CHECKPOINT_INTERVAL == 0:
                checkpoint(f"event_merge_pair_bucket_progress:{label}:{examined}")
            if pair in yielded:
                continue
            if len(yielded) >= max_pairs:
                failures["pair_budget_exhausted"] += 1
                return
            yielded.add(pair)
            yield pair


def _bucket_pairs(
    left_members: tuple[int, ...], right_members: tuple[int, ...] | None
) -> Iterator[tuple[int, int]]:
    if right_members is None:
        for index, left in enumerate(left_members):
            for right in left_members[index + 1 :]:
                yield left, right
        return
    for left in left_members:
        for right in right_members:
            if left != right:
                yield min(left, right), max(left, right)


def _overlapping_current_memberships(facts: Iterable[EventMergeFacts]) -> int:
    memberships: Counter[int] = Counter(
        raw_item_id for item in facts for raw_item_id in item.raw_item_ids
    )
    return sum(count > 1 for count in memberships.values())


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
