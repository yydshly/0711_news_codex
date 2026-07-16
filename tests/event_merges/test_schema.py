from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from newsradar.event_merges import (
    EventMergeFacts,
    MergeCandidateDetail,
    MergeCandidateDraft,
    MergeCandidateStatus,
    MergeCandidateType,
)

NOW = datetime(2026, 7, 16, 4, 0, tzinfo=UTC)


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
        strong_identities=(f"release:{event_id}",),
        object_entities=("NewsRadar",),
        actions=("released",),
        evidence_roots=(f"publisher:{event_id}",),
        key_numbers=("1.0",),
    )


def merge_draft(**updates: object) -> MergeCandidateDraft:
    values: dict[str, object] = {
        "left": event_facts(event_id=9, version_number=2),
        "right": event_facts(event_id=3, version_number=4),
        "candidate_type": MergeCandidateType.MANUAL_REVIEW,
        "input_fingerprint": "a" * 64,
        "reason_codes": ("same_object", "same_action"),
        "zh_reason": "对象和动作相同，但没有强身份，必须人工确认。",
        "zh_next_action": "核对两个事件的原始报道后确认或保持分开。",
    }
    values.update(updates)
    return MergeCandidateDraft(**values)


def test_merge_candidate_draft_normalizes_event_order() -> None:
    draft = merge_draft()

    assert (draft.left.event_id, draft.right.event_id) == (3, 9)
    assert (draft.left.version_number, draft.right.version_number) == (4, 2)


def test_merge_candidate_draft_requires_distinct_events() -> None:
    with pytest.raises(ValidationError, match="event_merge_pair_requires_distinct_events"):
        merge_draft(
            left=event_facts(event_id=3, version_number=1),
            right=event_facts(event_id=3, version_number=2),
        )


def test_merge_candidate_values_are_immutable() -> None:
    draft = merge_draft()

    with pytest.raises(ValidationError, match="frozen"):
        draft.zh_reason = "changed"
    with pytest.raises(ValidationError, match="frozen"):
        draft.left.visibility = "legacy"


def test_merge_candidate_draft_rejects_non_sha256_fingerprint() -> None:
    with pytest.raises(ValidationError, match="input_fingerprint"):
        merge_draft(input_fingerprint="not-a-fingerprint")


def test_merge_candidate_detail_is_an_immutable_ledger_value() -> None:
    draft = merge_draft()
    detail = MergeCandidateDetail(
        id=7,
        **draft.model_dump(),
        status=MergeCandidateStatus.PENDING,
        generated_operation_id=10,
        result_summary={},
        created_at=NOW,
        updated_at=NOW,
    )

    assert detail.left.event_id == 3
    assert detail.status is MergeCandidateStatus.PENDING
    with pytest.raises(ValidationError, match="frozen"):
        detail.status = MergeCandidateStatus.CONFIRMED
