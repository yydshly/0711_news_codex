import pytest
from pydantic import ValidationError

from newsradar.events.schema import EventEnrichment, ScoreBreakdown


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
