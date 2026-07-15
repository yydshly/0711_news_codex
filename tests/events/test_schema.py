import pytest
from pydantic import ValidationError

from newsradar.events import schema as event_schema
from newsradar.events.schema import EventEnrichment, ScoreBreakdown


def test_event_quality_v2_1_enums_and_pair_decision_are_stable() -> None:
    assert tuple(event_schema.EventTier) == (
        event_schema.EventTier.HOTSPOT,
        event_schema.EventTier.SIGNAL,
        event_schema.EventTier.AUDIT_ONLY,
    )
    assert tuple(event_schema.PairDecisionKind) == (
        event_schema.PairDecisionKind.DIRECT_MERGE,
        event_schema.PairDecisionKind.DIRECT_SEPARATE,
        event_schema.PairDecisionKind.MODEL_BOUNDARY,
    )
    decision = event_schema.PairFinalDecision(
        left_raw_item_id=1,
        right_raw_item_id=2,
        input_fingerprint="a" * 64,
        rule_score=0.61,
        rule_reasons=("shared_object_entity",),
        decision="separate",
        model_same_event=False,
        model_confidence=0.0,
    )
    assert decision.left_raw_item_id < decision.right_raw_item_id


def test_score_breakdown_rejects_out_of_range_values() -> None:
    with pytest.raises(ValidationError):
        ScoreBreakdown(
            ai_relevance=101,
            source_coverage=0,
            source_authority=0,
            recency=0,
            engagement_velocity=0,
            novelty=0,
            importance=101,
            credibility=0,
            heat=0,
            reasons=[],
        )


def test_event_enrichment_rejects_confidence_outside_unit_interval() -> None:
    with pytest.raises(ValidationError):
        EventEnrichment(
            zh_title="标题",
            zh_summary="摘要",
            why_it_matters="重要性",
            origin="model",
            confidence=1.01,
        )
