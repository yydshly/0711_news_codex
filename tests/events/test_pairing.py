from datetime import UTC, datetime

import pytest

from newsradar.events.clustering import (
    candidate_pairs,
    cluster_candidates,
    evaluate_pair_rules,
)
from newsradar.events.pairing import (
    finalize_pair_decision,
    pair_input_fingerprint,
    safe_root_identity,
)
from newsradar.events.schema import (
    ClusterItem,
    PairDecisionKind,
    PairRuleDecision,
    PairSemanticDecision,
)


def test_model_cannot_merge_without_structural_anchor() -> None:
    rule = PairRuleDecision(
        left_raw_item_id=1,
        right_raw_item_id=2,
        score=0.62,
        reasons=("within_72_hours",),
        structural_anchor=False,
        kind=PairDecisionKind.MODEL_BOUNDARY,
    )
    semantic = PairSemanticDecision(
        decision="same_event",
        confidence=0.99,
        rationale="similar topic",
        origin="model",
    )

    final = finalize_pair_decision(rule, semantic, "a" * 64)

    assert final.decision == "separate"


def test_high_confidence_model_can_confirm_anchored_boundary_pair() -> None:
    rule = PairRuleDecision(
        left_raw_item_id=1,
        right_raw_item_id=2,
        score=0.68,
        reasons=("shared_object_entity", "same_action"),
        structural_anchor=True,
        kind=PairDecisionKind.MODEL_BOUNDARY,
    )
    semantic = PairSemanticDecision(
        decision="same_event",
        confidence=0.91,
        rationale="same release",
        origin="model",
    )

    assert finalize_pair_decision(rule, semantic, "b" * 64).decision == "merge"


@pytest.mark.parametrize(
    "semantic",
    [
        None,
        PairSemanticDecision(
            decision="uncertain",
            confidence=0.99,
            rationale="insufficient evidence",
            origin="model",
        ),
        PairSemanticDecision(
            decision="different_event",
            confidence=0.99,
            rationale="different release",
            origin="model",
        ),
        PairSemanticDecision(
            decision="same_event",
            confidence=0.84,
            rationale="below threshold",
            origin="model",
        ),
    ],
)
def test_boundary_pair_fails_closed_without_high_confidence_same_event(
    semantic: PairSemanticDecision | None,
) -> None:
    rule = PairRuleDecision(
        left_raw_item_id=1,
        right_raw_item_id=2,
        score=0.68,
        reasons=("shared_object_entity", "same_action"),
        structural_anchor=True,
        kind=PairDecisionKind.MODEL_BOUNDARY,
    )

    final = finalize_pair_decision(rule, semantic, "c" * 64)

    assert final.decision == "separate"
    assert final.model_same_event is (
        None
        if semantic is None or semantic.decision == "uncertain"
        else semantic.decision == "same_event"
    )


def test_pair_fingerprint_is_order_independent_and_excludes_url_query_data() -> None:
    timestamp = datetime(2026, 7, 15, 9, 15, tzinfo=UTC)
    left = ClusterItem(
        raw_item_id=2,
        title="OpenAI launches a model",
        entities=("model:orion",),
        original_url="https://news.example.test/posts/orion?token=secret",
        published_at=timestamp,
    )
    right = ClusterItem(
        raw_item_id=1,
        title="OpenAI model launch",
        entities=("model:orion",),
        canonical_url="https://official.example.test/orion?utm_source=feed",
        published_at=timestamp,
    )

    assert pair_input_fingerprint(left, right) == pair_input_fingerprint(right, left)
    assert safe_root_identity(left) == "news.example.test/posts/orion"


def test_pair_fingerprint_changes_when_bounded_model_context_changes() -> None:
    left = ClusterItem(
        raw_item_id=1,
        title="OpenAI launches Orion",
        summary="Initial release details",
        entities=("model:orion",),
        source_nature="first_party",
        publisher_name="OpenAI",
    )
    right = left.model_copy(update={"raw_item_id": 2})
    baseline = pair_input_fingerprint(left, right)

    for update in (
        {"summary": "Updated release details"},
        {"source_nature": "professional_media"},
        {"publisher_name": "Reuters"},
        {"entities": ("model:orion", "product:api")},
    ):
        changed = right.model_copy(update=update)
        assert pair_input_fingerprint(left, changed) != baseline


def test_rule_pairs_merge_identical_canonical_evidence_directly() -> None:
    now = datetime(2026, 7, 15, 9, tzinfo=UTC)
    left = ClusterItem(
        raw_item_id=2,
        title="OpenAI launches Orion model",
        canonical_url="https://official.example.test/orion",
        published_at=now,
    )
    right = left.model_copy(update={"raw_item_id": 1})

    rule = evaluate_pair_rules(left, right)

    assert rule.kind is PairDecisionKind.DIRECT_MERGE
    assert rule.structural_anchor is True
    assert rule.left_raw_item_id == 1


def test_shared_entity_without_same_action_is_not_a_structural_anchor() -> None:
    now = datetime(2026, 7, 15, 9, tzinfo=UTC)
    left = ClusterItem(
        raw_item_id=1,
        title="Orion model availability",
        entities=("model:orion",),
        published_at=now,
    )
    right = ClusterItem(
        raw_item_id=2,
        title="A technical review of Orion",
        entities=("model:orion",),
        published_at=now,
    )

    rule = evaluate_pair_rules(left, right)

    assert rule.structural_anchor is False
    assert rule.kind is PairDecisionKind.DIRECT_SEPARATE


def test_launch_with_only_shared_organization_is_not_a_structural_anchor() -> None:
    now = datetime(2026, 7, 15, 9, tzinfo=UTC)
    left = ClusterItem(
        raw_item_id=1,
        title="OpenAI releases Atlas model",
        entities=("organization:openai",),
        published_at=now,
    )
    right = left.model_copy(update={"raw_item_id": 2})

    rule = evaluate_pair_rules(left, right)

    assert rule.structural_anchor is False
    assert rule.kind is PairDecisionKind.DIRECT_SEPARATE


def test_anchored_borderline_title_similarity_uses_model_boundary() -> None:
    now = datetime(2026, 7, 15, 9, tzinfo=UTC)
    left = ClusterItem(
        raw_item_id=1,
        title="OpenAI launches Orion reasoning model",
        entities=("model:orion",),
        published_at=now,
    )
    right = ClusterItem(
        raw_item_id=2,
        title="Orion reasoning model released by OpenAI",
        entities=("model:orion",),
        published_at=now,
    )

    rule = evaluate_pair_rules(left, right)

    assert rule.structural_anchor is True
    assert rule.kind is PairDecisionKind.MODEL_BOUNDARY
    assert "model_boundary_title_similarity" in rule.reasons


def test_candidate_pairs_are_blocked_and_not_global_cross_product() -> None:
    now = datetime(2026, 7, 15, 9, tzinfo=UTC)
    items = (
        ClusterItem(
            raw_item_id=1, title="Alpha", entities=("model:alpha",), published_at=now
        ),
        ClusterItem(
            raw_item_id=2,
            title="Alpha report",
            entities=("model:alpha",),
            published_at=now,
        ),
        ClusterItem(
            raw_item_id=3,
            title="Unrelated",
            entities=("model:beta",),
            published_at=now,
        ),
    )

    assert candidate_pairs(items) == ((items[0], items[1]),)


def test_cluster_only_unions_explicit_merge_pair_decisions() -> None:
    now = datetime(2026, 7, 15, 9, tzinfo=UTC)
    left = ClusterItem(
        raw_item_id=1,
        title="OpenAI launches Orion model",
        entities=("model:orion",),
        published_at=now,
    )
    right = left.model_copy(update={"raw_item_id": 2})
    rule = evaluate_pair_rules(left, right)
    merged = finalize_pair_decision(rule, None, pair_input_fingerprint(left, right))

    clusters = cluster_candidates(
        (left, right), {(1, 2): merged}
    )

    assert len(clusters) == 1
    assert clusters[0].raw_item_ids == (1, 2)
