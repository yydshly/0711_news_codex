from datetime import UTC, datetime

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
        same_event=True,
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
        same_event=True,
        confidence=0.91,
        rationale="same release",
        origin="model",
    )

    assert finalize_pair_decision(rule, semantic, "b" * 64).decision == "merge"


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
