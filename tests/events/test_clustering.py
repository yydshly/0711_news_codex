from __future__ import annotations

from datetime import UTC, datetime, timedelta

from newsradar.events.clustering import CLUSTER_RULE_VERSION, cluster_candidates, compare_items
from newsradar.events.schema import ClusterItem

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)


def item(**changes: object) -> ClusterItem:
    data: dict[str, object] = {
        "raw_item_id": 1,
        "title": "Acme launches Model X",
        "canonical_url_hash": None,
        "title_fingerprint": None,
        "entities": (),
        "published_at": NOW,
    }
    data.update(changes)
    return ClusterItem(**data)


def test_same_canonical_url_is_a_strong_match() -> None:
    decision = compare_items(
        item(canonical_url_hash="same"), item(raw_item_id=2, canonical_url_hash="same")
    )

    assert decision.matched
    assert decision.score == 1.0
    assert "same_canonical_url" in decision.reasons


def test_same_company_different_actions_do_not_merge() -> None:
    left = item(entities=("organization:acme",), title="Acme launches Model X")
    right = item(
        raw_item_id=2,
        entities=("organization:acme",),
        title="Acme acquires DataCo",
    )

    decision = compare_items(left, right)

    assert decision.matched is False
    assert "conflicting_action" in decision.reasons


def test_common_original_url_is_a_strong_match() -> None:
    decision = compare_items(
        item(original_url="https://publisher.test/story"),
        item(raw_item_id=2, original_url="https://publisher.test/story"),
    )

    assert decision.matched
    assert "same_original_url" in decision.reasons


def test_candidate_generation_only_merges_blocked_items_within_48_hours() -> None:
    first = item(raw_item_id=1, title_fingerprint="model-x")
    nearby = item(
        raw_item_id=2, title_fingerprint="model-x", published_at=NOW + timedelta(hours=47)
    )
    old = item(raw_item_id=3, title_fingerprint="model-x", published_at=NOW + timedelta(hours=49))
    unblocked = item(raw_item_id=4, title="Model X coverage", published_at=NOW)

    clusters = cluster_candidates((old, unblocked, nearby, first))

    assert CLUSTER_RULE_VERSION == "cluster-v1"
    assert [cluster.raw_item_ids for cluster in clusters] == [(1, 2), (3,), (4,)]
    assert "same_title_fingerprint" in clusters[0].reasons


def test_shared_generic_entity_is_not_a_blocking_key() -> None:
    left = item(raw_item_id=1, entities=("organization:model",))
    right = item(raw_item_id=2, entities=("organization:model",))

    assert cluster_candidates((left, right))[0].raw_item_ids == (1,)
