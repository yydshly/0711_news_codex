from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from newsradar.events import clustering
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


def test_same_company_action_and_day_do_not_merge_different_object_entities() -> None:
    left = item(
        entities=("organization:acme", "model:alpha"),
        title="Acme launches Alpha",
    )
    right = item(
        raw_item_id=2,
        entities=("organization:acme", "model:beta"),
        title="Acme launches Beta",
    )

    decision = compare_items(left, right)

    assert decision.matched is False
    assert "shared_organization" in decision.reasons
    assert "shared_object_entity" not in decision.reasons


def test_same_company_action_and_shared_object_entity_is_a_compatible_weak_match() -> None:
    left = item(
        entities=("organization:acme", "model:alpha"),
        title="Acme launches Alpha",
    )
    right = item(
        raw_item_id=2,
        entities=("organization:acme", "model:alpha"),
        title="Acme launches its Alpha system",
    )

    decision = compare_items(left, right)

    assert decision.matched
    assert "shared_object_entity" in decision.reasons


def test_same_upstream_root_is_a_strong_match_without_explicit_object_entity() -> None:
    left = item(
        canonical_url="https://media-a.test/alpha",
        original_url="https://acme.test/releases/alpha",
        title="Acme introduces its newest system",
    )
    right = item(
        raw_item_id=2,
        canonical_url="https://media-b.test/coverage",
        original_url="https://acme.test/releases/alpha",
        title="The latest Acme release arrives",
    )

    decision = compare_items(left, right)

    assert decision.matched
    assert "same_evidence_root" in decision.reasons


def test_new_media_source_on_same_root_keeps_anchor_candidate_identity() -> None:
    first = item(
        raw_item_id=1,
        canonical_url="https://media-a.test/coverage",
        original_url="https://acme.test/releases/alpha",
        title="Acme release coverage",
        title_fingerprint="z-release",
    )
    later = item(
        raw_item_id=2,
        canonical_url="https://media-b.test/story",
        original_url="https://acme.test/releases/alpha",
        title="A closer look at the release",
        title_fingerprint="a-release",
    )

    first_key = cluster_candidates((first,))[0].candidate_key
    combined = cluster_candidates((first, later))[0]

    assert combined.raw_item_ids == (1, 2)
    assert combined.candidate_key == first_key


def test_same_resolved_publisher_url_is_a_strong_match() -> None:
    decision = compare_items(
        item(canonical_url="https://publisher.test/story"),
        item(raw_item_id=2, canonical_url="https://publisher.test/story"),
    )

    assert decision.matched
    assert "same_canonical_url" in decision.reasons


def test_same_canonical_url_overrides_conflicting_title_actions() -> None:
    decision = compare_items(
        item(canonical_url="https://publisher.test/story", title="Acme launches Model X"),
        item(
            raw_item_id=2,
            canonical_url="https://publisher.test/story",
            title="Acme acquires DataCo",
        ),
    )

    assert decision.matched
    assert "same_canonical_url" in decision.reasons
    assert "conflicting_action" not in decision.reasons


@pytest.mark.parametrize("identity", ["repository_id", "paper_id"])
def test_repository_and_paper_identity_override_conflicting_title_actions(identity: str) -> None:
    decision = compare_items(
        item(**{identity: "shared", "title": "Acme launches Model X"}),
        item(raw_item_id=2, **{identity: "shared", "title": "Acme acquires DataCo"}),
    )

    assert decision.matched
    assert f"same_{identity}" in decision.reasons


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


def test_candidate_generation_compares_only_shared_blocking_buckets(monkeypatch) -> None:
    first = item(raw_item_id=1, title_fingerprint="shared")
    second = item(raw_item_id=2, title_fingerprint="shared")
    unrelated = tuple(
        item(raw_item_id=index, title_fingerprint=f"other-{index}") for index in range(3, 20)
    )
    compared: list[tuple[int, int]] = []
    real_compare = clustering.compare_items

    def recording_compare(left: ClusterItem, right: ClusterItem):
        compared.append((left.raw_item_id, right.raw_item_id))
        return real_compare(left, right)

    monkeypatch.setattr(clustering, "compare_items", recording_compare)

    cluster_candidates((first, second, *unrelated))

    assert compared == [(1, 2)]
