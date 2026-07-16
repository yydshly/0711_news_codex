from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from newsradar.events import clustering
from newsradar.events.clustering import (
    CLUSTER_RULE_VERSION,
    candidate_pairs,
    cluster_candidates,
    compare_items,
    evaluate_pair_rules,
)
from newsradar.events.entities import extract_entities
from newsradar.events.schema import ClusterItem, PairDecisionKind, RawItemText

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


def test_cross_publisher_semantic_merge_requires_entity_action_time_and_title() -> None:
    left = item(
        title="OpenAI launches Orion reasoning model",
        publisher_name="Official",
        entities=("organization:openai", "model:orion"),
        published_at=NOW,
    )
    right = item(
        raw_item_id=2,
        title="OpenAI releases new Orion model for developers",
        publisher_name="Media A",
        entities=("organization:openai", "model:orion"),
        published_at=NOW + timedelta(hours=3),
    )

    decision = compare_items(left, right)

    assert decision.matched is True
    assert {
        "shared_non_generic_entity",
        "same_action",
        "within_48_hours",
        "safe_title_similarity",
    } <= set(decision.reasons)


def test_same_entity_and_window_with_different_action_stays_separate() -> None:
    left = item(title="Regulator investigates Orion", entities=("model:orion",))
    right = item(
        raw_item_id=2,
        title="OpenAI launches Orion",
        entities=("model:orion",),
        published_at=NOW + timedelta(hours=1),
    )

    assert compare_items(left, right).matched is False


def test_generic_ai_words_never_create_candidate_pair() -> None:
    left = item(raw_item_id=1, title="AI model market grows", entities=("model:ai",))
    right = item(
        raw_item_id=2,
        title="AI model safety debate",
        entities=("model:model",),
    )

    assert candidate_pairs((left, right)) == ()


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
        publisher_name="Shared Publisher",
    )
    right = item(
        raw_item_id=2,
        entities=("organization:acme", "model:beta"),
        title="Acme launches Beta",
        publisher_name="Shared Publisher",
    )

    decision = compare_items(left, right)

    assert decision.matched is False
    assert "disjoint_object_entities" in decision.reasons
    assert evaluate_pair_rules(left, right).kind is PairDecisionKind.DIRECT_SEPARATE


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


def test_cluster_v3_does_not_merge_shared_company_without_same_object_and_action() -> None:
    left = item(
        entities=("organization:openai", "model:orion"),
        title="OpenAI launches Orion model",
    )
    right = item(
        raw_item_id=2,
        entities=("organization:openai", "organization:example"),
        title="OpenAI acquires Example Corp",
    )

    assert compare_items(left, right).matched is False


@pytest.mark.parametrize(
    ("offset", "expected"),
    [(timedelta(hours=48), True), (timedelta(hours=48, seconds=1), False)],
)
def test_cluster_v3_requires_same_object_action_within_48_hours(
    offset: timedelta, expected: bool
) -> None:
    left = item(
        entities=("model:orion",),
        title="OpenAI releases Orion model",
    )
    right = item(
        raw_item_id=2,
        entities=("model:orion",),
        title="OpenAI released Orion model",
        published_at=NOW + offset,
    )

    assert compare_items(left, right).matched is expected


def test_title_fingerprint_needs_same_publisher_or_evidence_root() -> None:
    left = item(title_fingerprint="same", publisher_name="Media A")
    unrelated = item(raw_item_id=2, title_fingerprint="same", publisher_name="Media B")
    same_publisher = unrelated.model_copy(update={"publisher_name": "Media A"})

    assert compare_items(left, unrelated).matched is False
    assert compare_items(left, same_publisher).matched is True


def test_publisher_suffix_is_removed_before_safe_title_comparison() -> None:
    left = item(
        title="OpenAI launches Orion model",
        publisher_name="Official",
        entities=("model:orion",),
    )
    right = item(
        raw_item_id=2,
        title="OpenAI launches Orion model - Media A",
        publisher_name="Media A",
        entities=("model:orion",),
        published_at=NOW + timedelta(hours=2),
    )

    decision = compare_items(left, right)

    assert decision.matched is True
    assert "safe_title_similarity" in decision.reasons


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


def test_canonical_and_original_url_identity_bypass_semantic_time_window() -> None:
    shared_url = "https://publisher.test/releases/orion"
    left = item(
        raw_item_id=1,
        canonical_url=shared_url,
        title="OpenAI launches Orion",
        published_at=NOW,
    )
    right = item(
        raw_item_id=2,
        original_url=shared_url,
        title="A later mirror with a conflicting headline",
        published_at=NOW + timedelta(days=10),
    )

    clusters = cluster_candidates((left, right))

    assert [cluster.raw_item_ids for cluster in clusters] == [(1, 2)]
    assert "same_evidence_root" in clusters[0].reasons


@pytest.mark.parametrize("identity", ["repository_id", "paper_id"])
def test_repository_and_paper_identity_override_conflicting_title_actions(identity: str) -> None:
    decision = compare_items(
        item(**{identity: "shared", "title": "Acme launches Model X"}),
        item(raw_item_id=2, **{identity: "shared", "title": "Acme acquires DataCo"}),
    )

    assert decision.matched
    assert f"same_{identity}" in decision.reasons


def test_candidate_generation_only_merges_blocked_items_within_48_hours() -> None:
    first = item(raw_item_id=1, title_fingerprint="model-x", publisher_name="Publisher")
    nearby = item(
        raw_item_id=2,
        title_fingerprint="model-x",
        published_at=NOW + timedelta(hours=47),
        publisher_name="Publisher",
    )
    old = item(
        raw_item_id=3,
        title_fingerprint="model-x",
        published_at=NOW + timedelta(hours=49),
        publisher_name="Publisher",
    )
    unblocked = item(raw_item_id=4, title="Model X coverage", published_at=NOW)

    clusters = cluster_candidates((old, unblocked, nearby, first))

    assert CLUSTER_RULE_VERSION == "cluster-v3"
    assert [cluster.raw_item_ids for cluster in clusters] == [(1, 2), (3,), (4,)]
    assert "same_title_fingerprint" in clusters[0].reasons


def test_cluster_v3_candidate_identity_does_not_reuse_legacy_identity() -> None:
    candidate_key = cluster_candidates((item(),))[0].candidate_key
    legacy_value = "title:acme launches model x|launch|2026-07-12"
    legacy_key = f"event-v2:{sha256(legacy_value.encode()).hexdigest()[:16]}"

    assert candidate_key.startswith("event-v2:")
    assert candidate_key != legacy_key


def test_core_identity_is_object_and_action_independent_of_event_day() -> None:
    first = cluster_candidates(
        (
            item(
                entities=("model:orion",),
                title="OpenAI launches Orion model",
                published_at=NOW,
            ),
        )
    )[0]
    later = cluster_candidates(
        (
            item(
                raw_item_id=2,
                entities=("model:orion",),
                title="Orion model released by OpenAI",
                published_at=NOW + timedelta(days=3),
            ),
        )
    )[0]

    assert first.candidate_key != later.candidate_key
    assert first.metadata["_core_identity"] == later.metadata["_core_identity"]
    assert first.metadata["_core_identity"] == "model:orion|launch"


def test_candidates_without_a_core_object_do_not_share_a_novelty_identity() -> None:
    candidate = cluster_candidates(
        (item(title="A general AI industry report", entities=("organization:openai",)),)
    )[0]

    assert candidate.metadata["_core_identity"] is None


@pytest.mark.parametrize("identity", ["canonical_url", "repository_id", "paper_id"])
def test_immutable_identity_candidate_key_does_not_depend_on_date_or_anchor(
    identity: str,
) -> None:
    value = "https://official.test/release" if identity == "canonical_url" else "shared-id"
    first = cluster_candidates(
        (item(raw_item_id=1, published_at=NOW, **{identity: value}),)
    )[0]
    later = cluster_candidates(
        (item(raw_item_id=99, published_at=NOW + timedelta(days=10), **{identity: value}),)
    )[0]

    assert first.candidate_key == later.candidate_key


def test_real_gpt5_titles_with_low_similarity_remain_separate() -> None:
    left_title = "OpenAI releases GPT-5 for developers"
    right_title = "GPT-5 model released with new coding capabilities"
    left_entities = tuple(
        entity.canonical_key
        for entity in extract_entities(RawItemText(title=left_title))
    )
    right_entities = tuple(
        entity.canonical_key
        for entity in extract_entities(RawItemText(title=right_title))
    )

    left = item(
        raw_item_id=1,
        title=left_title,
        canonical_url="https://official.test/gpt5",
        entities=left_entities,
    )
    right = item(
        raw_item_id=2,
        title=right_title,
        canonical_url="https://media.test/gpt5",
        entities=right_entities,
        published_at=NOW + timedelta(hours=3),
    )

    decision = compare_items(left, right)
    clusters = cluster_candidates((left, right))

    assert decision.matched is False
    assert "low_title_similarity" in decision.reasons
    assert [cluster.raw_item_ids for cluster in clusters] == [(1,), (2,)]
    assert "model:gpt-5" in left_entities
    assert "model:gpt-5" in right_entities


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Research team publishes a new paper", "launch"),
        ("Research team published a new paper", "launch"),
        ("Acme open-sources its toolkit", "launch"),
        ("Acme open sourced its toolkit", "launch"),
        ("Acme open source toolkit", "launch"),
        ("Open research source report", None),
        ("Acme opens source office", None),
    ],
)
def test_release_action_recognizes_publish_and_open_source_phrases_only(
    title: str, expected: str | None
) -> None:
    assert clustering._action(title) == expected


@pytest.mark.parametrize(
    ("entity", "left_title", "right_title"),
    [
        (
            "paper:interpretable-agents",
            "Team publishes Interpretable Agents paper",
            "Interpretable Agents paper published by Team",
        ),
        (
            "project:openai/codex",
            "OpenAI open-sources openai/codex",
            "openai/codex was open sourced by OpenAI",
        ),
    ],
)
def test_publish_and_open_source_reports_cluster_across_urls_within_48_hours(
    entity: str, left_title: str, right_title: str
) -> None:
    clusters = cluster_candidates(
        (
            item(
                raw_item_id=1,
                title=left_title,
                canonical_url="https://official.test/release",
                entities=(entity,),
            ),
            item(
                raw_item_id=2,
                title=right_title,
                canonical_url="https://media.test/story",
                entities=(entity,),
                published_at=NOW + timedelta(hours=3),
            ),
        )
    )

    assert [cluster.raw_item_ids for cluster in clusters] == [(1, 2)]


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


@pytest.mark.parametrize("count", [100, 200])
def test_dense_component_window_check_does_not_rescan_members(
    monkeypatch, count: int
) -> None:
    find_calls = 0
    real_find = clustering._find

    def recording_find(parents: list[int], index: int) -> int:
        nonlocal find_calls
        find_calls += 1
        return real_find(parents, index)

    monkeypatch.setattr(clustering, "_find", recording_find)
    dense = tuple(
        item(
            raw_item_id=index,
            title="Orion model released",
            entities=("model:orion",),
            published_at=NOW + timedelta(minutes=index),
        )
        for index in range(1, count + 1)
    )

    clusters = cluster_candidates(dense)

    assert [cluster.raw_item_ids for cluster in clusters] == [
        tuple(range(1, count + 1))
    ]
    assert find_calls <= 10 * count * count
