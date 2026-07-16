"""Read-only event scanning with isolated candidate/audit writes."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newsradar.db.models import EventMergeCandidateRecord, EventRecord
from newsradar.event_merges.facts import EVENT_MERGE_RULE_VERSION, load_event_facts
from newsradar.event_merges.repository import EventMergeCandidateRepository
from newsradar.event_merges.rules import classify_pair
from newsradar.event_merges.schema import EventMergeFacts
from newsradar.events.operation_snapshots import latest_complete_event_snapshot

_TIME_BUCKET_SECONDS = 48 * 60 * 60


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

        pairs, overlapping_memberships = _bounded_event_pairs(facts_by_id.values())
        candidate_types: Counter[str] = Counter()
        for left_id, right_id in pairs:
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
        facts_values = tuple(facts_by_id.values())
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
            pair_count=len(pairs),
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


def _bounded_event_pairs(
    facts_values: Iterable[EventMergeFacts],
) -> tuple[tuple[tuple[int, int], ...], int]:
    facts = tuple(facts_values)
    raw_index: defaultdict[int, list[int]] = defaultdict(list)
    strong_index: defaultdict[str, list[int]] = defaultdict(list)
    object_time_index: defaultdict[tuple[str, int], list[int]] = defaultdict(list)
    pairs: set[tuple[int, int]] = set()
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

    for members in (*raw_index.values(), *strong_index.values()):
        _add_pairs(pairs, members)
    for (entity, bucket), members in object_time_index.items():
        _add_cross_pairs(pairs, members, object_time_index.get((entity, bucket + 1), ()))
        _add_pairs(pairs, members)
    overlap_count = sum(len(set(members)) > 1 for members in raw_index.values())
    return tuple(sorted(pairs)), overlap_count


def _add_pairs(pairs: set[tuple[int, int]], members: Iterable[int]) -> None:
    unique = tuple(sorted(set(members)))
    for index, left in enumerate(unique):
        for right in unique[index + 1 :]:
            pairs.add((left, right))


def _add_cross_pairs(
    pairs: set[tuple[int, int]], left_members: Iterable[int], right_members: Iterable[int]
) -> None:
    for left in set(left_members):
        for right in set(right_members):
            if left != right:
                pairs.add((min(left, right), max(left, right)))


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
