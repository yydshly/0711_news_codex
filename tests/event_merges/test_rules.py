from datetime import UTC, datetime, timedelta

import pytest

from newsradar.event_merges.rules import classify_pair
from newsradar.event_merges.schema import EventMergeFacts, MergeCandidateType

NOW = datetime(2026, 7, 16, 4, tzinfo=UTC)


def _facts(
    *,
    event_id: int,
    algorithms: tuple[str, ...] = ("cluster-v3",),
    raw_item_ids: tuple[int, ...] = (10,),
    strong_identities: tuple[str, ...] = (),
    objects: tuple[str, ...] = (),
    actions: tuple[str, ...] = (),
    key_numbers: tuple[str, ...] = (),
    publishers: tuple[str, ...] = (),
    published_at: tuple[datetime, ...] = (NOW,),
) -> EventMergeFacts:
    return EventMergeFacts(
        event_id=event_id,
        version_number=1,
        visibility="current",
        canonical_key=f"event-{event_id}",
        algorithm_versions=algorithms,
        raw_item_ids=raw_item_ids,
        source_ids=(f"source-{event_id}",),
        publishers=publishers,
        published_at=published_at,
        safe_url_identities=strong_identities,
        strong_identities=strong_identities,
        object_entities=objects,
        actions=actions,
        evidence_roots=(),
        key_numbers=key_numbers,
    )


def test_exact_old_and_current_membership_is_legacy_identity_candidate() -> None:
    left = _facts(event_id=1, algorithms=("cluster-v2",), raw_item_ids=(10, 11))
    right = _facts(event_id=2, algorithms=("cluster-v3",), raw_item_ids=(10, 11))

    draft = classify_pair(left, right, latest_snapshot_event_ids=frozenset({2}))

    assert draft is not None
    assert draft.candidate_type is MergeCandidateType.LEGACY_IDENTITY


def test_subset_membership_is_never_automatic_legacy_retirement() -> None:
    left = _facts(event_id=1, algorithms=("cluster-v2",), raw_item_ids=(10,))
    right = _facts(event_id=2, algorithms=("cluster-v3",), raw_item_ids=(10, 11))

    draft = classify_pair(left, right, latest_snapshot_event_ids=frozenset({2}))

    assert draft is None or draft.candidate_type is MergeCandidateType.MANUAL_REVIEW


def test_legacy_identity_requires_latest_snapshot_to_reference_current_event() -> None:
    left = _facts(event_id=1, algorithms=("cluster-v2",), raw_item_ids=(10, 11))
    right = _facts(event_id=2, algorithms=("cluster-v3",), raw_item_ids=(10, 11))

    assert classify_pair(left, right, frozenset()) is None


def test_same_real_original_url_is_deterministic_merge() -> None:
    identity = ("www.reuters.com/story/1",)
    left = _facts(event_id=1, strong_identities=identity)
    right = _facts(event_id=2, strong_identities=identity)

    draft = classify_pair(left, right, frozenset())

    assert draft is not None
    assert draft.candidate_type is MergeCandidateType.DETERMINISTIC_MERGE


def test_same_object_action_and_time_is_manual_not_automatic() -> None:
    left = _facts(event_id=1, objects=("model:orion",), actions=("release",))
    right = _facts(event_id=2, objects=("model:orion",), actions=("release",))

    draft = classify_pair(left, right, frozenset())

    assert draft is not None
    assert draft.candidate_type is MergeCandidateType.MANUAL_REVIEW


@pytest.mark.parametrize("conflict", ["object", "action", "key_number"])
def test_conflicting_facts_do_not_create_merge_candidate(conflict: str) -> None:
    common = {
        "objects": ("model:orion",),
        "actions": ("release",),
        "key_numbers": ("128",),
    }
    other = dict(common)
    other[{"object": "objects", "action": "actions", "key_number": "key_numbers"}[conflict]] = {
        "object": ("model:atlas",),
        "action": ("acquisition",),
        "key_number": ("256",),
    }[conflict]

    assert classify_pair(
        _facts(event_id=1, **common), _facts(event_id=2, **other), frozenset()
    ) is None


@pytest.mark.parametrize("signal", ["organization", "title", "time", "model"])
def test_weak_signal_alone_does_not_create_candidate(signal: str) -> None:
    values: dict[str, object] = {}
    if signal == "organization":
        values["objects"] = ("organization:openai",)
    elif signal == "time":
        values["published_at"] = (NOW, NOW + timedelta(minutes=5))
    # Title similarity and model confidence are intentionally absent from bounded facts.

    assert classify_pair(
        _facts(event_id=1, **values), _facts(event_id=2, **values), frozenset()
    ) is None
