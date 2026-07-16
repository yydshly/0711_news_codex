"""Fail-closed merge-candidate classification rules."""

from __future__ import annotations

from datetime import timedelta

from newsradar.event_merges.facts import EVENT_MERGE_RULE_VERSION, merge_input_fingerprint
from newsradar.event_merges.schema import (
    EventMergeFacts,
    MergeCandidateDraft,
    MergeCandidateType,
)
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS

_CURRENT_CLUSTER = EVENT_ALGORITHM_VERSIONS["cluster"]
_MANUAL_TIME_BOUND = timedelta(hours=48)


def classify_pair(
    left: EventMergeFacts,
    right: EventMergeFacts,
    latest_snapshot_event_ids: frozenset[int],
) -> MergeCandidateDraft | None:
    if _exact_cross_algorithm_identity(left, right, latest_snapshot_event_ids):
        return _draft(
            MergeCandidateType.LEGACY_IDENTITY,
            left,
            right,
            reason_codes=("exact_cross_algorithm_membership",),
            zh_reason="旧算法与当前算法事件包含完全相同的原始条目。",
            zh_next_action="保留当前算法事件，并把旧身份转入历史目录。",
        )
    if _conflicting_facts(left, right):
        return None
    if set(left.strong_identities) & set(right.strong_identities):
        return _draft(
            MergeCandidateType.DETERMINISTIC_MERGE,
            left,
            right,
            reason_codes=("same_strong_identity",),
            zh_reason="两个事件共享同一个可验证的原始内容标识。",
            zh_next_action="复核原始媒体后应用确定性合并。",
        )
    if _manual_review_boundary(left, right):
        return _draft(
            MergeCandidateType.MANUAL_REVIEW,
            left,
            right,
            reason_codes=("same_object_action_without_strong_identity",),
            zh_reason="对象、动作和时间接近，但缺少可自动证明同一事件的强标识。",
            zh_next_action="人工核对两侧原始报道后确认合并或保持分开。",
        )
    return None


def _exact_cross_algorithm_identity(
    left: EventMergeFacts,
    right: EventMergeFacts,
    latest_snapshot_event_ids: frozenset[int],
) -> bool:
    if not left.raw_item_ids or left.raw_item_ids != right.raw_item_ids:
        return False
    left_current = _CURRENT_CLUSTER in left.algorithm_versions
    right_current = _CURRENT_CLUSTER in right.algorithm_versions
    if left_current == right_current:
        return False
    current = left if left_current else right
    legacy = right if left_current else left
    return (
        current.event_id in latest_snapshot_event_ids
        and bool(legacy.algorithm_versions)
        and any(version != _CURRENT_CLUSTER for version in legacy.algorithm_versions)
    )


def _conflicting_facts(left: EventMergeFacts, right: EventMergeFacts) -> bool:
    return any(
        first and second and not (set(first) & set(second))
        for first, second in (
            (left.object_entities, right.object_entities),
            (left.actions, right.actions),
            (left.key_numbers, right.key_numbers),
        )
    )


def _manual_review_boundary(left: EventMergeFacts, right: EventMergeFacts) -> bool:
    if not (set(left.object_entities) & set(right.object_entities)):
        return False
    if not (set(left.actions) & set(right.actions)):
        return False
    return any(
        abs(left_time - right_time) <= _MANUAL_TIME_BOUND
        for left_time in left.published_at
        for right_time in right.published_at
    )


def _draft(
    candidate_type: MergeCandidateType,
    left: EventMergeFacts,
    right: EventMergeFacts,
    *,
    reason_codes: tuple[str, ...],
    zh_reason: str,
    zh_next_action: str,
) -> MergeCandidateDraft:
    return MergeCandidateDraft(
        left=left,
        right=right,
        candidate_type=candidate_type,
        algorithm_version=EVENT_MERGE_RULE_VERSION,
        input_fingerprint=merge_input_fingerprint(left, right),
        reason_codes=reason_codes,
        zh_reason=zh_reason,
        zh_next_action=zh_next_action,
    )
