from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import log10

import pytest

from newsradar.events.quality import QualityInputs, build_score_input
from newsradar.events.schema import (
    CandidateCluster,
    ClusterItem,
    EvidenceAssessment,
    EvidenceRole,
)

NOW = datetime(2026, 7, 14, 12, tzinfo=UTC)


def quality_candidate(*, occurred_at: datetime | None = None) -> CandidateCluster:
    return CandidateCluster(
        candidate_key="event-v2:orion",
        title="OpenAI launches Orion model",
        items=(
            ClusterItem(raw_item_id=1, published_at=NOW - timedelta(hours=2)),
            ClusterItem(raw_item_id=2, published_at=NOW - timedelta(hours=1)),
        ),
        raw_item_ids=(1, 2),
        occurred_at=occurred_at or NOW - timedelta(hours=2),
    )


def root(
    raw_item_id: int,
    key: str,
    role: EvidenceRole = EvidenceRole.PROFESSIONAL_MEDIA,
    *,
    independent: bool = True,
) -> EvidenceAssessment:
    return EvidenceAssessment(
        raw_item_id=raw_item_id,
        role=role,
        root_evidence_key=key,
        independent=independent,
    )


def build(**changes: object):
    values: dict[str, object] = {
        "candidate": quality_candidate(),
        "evidence": (
            root(1, "official:orion", EvidenceRole.OFFICIAL),
            root(2, "media:orion"),
        ),
        "relevance_by_item": {1: 100, 2: 80},
        "authority_by_item": {1: 5, 2: 4},
        "engagement_by_item": {1: {"score": 120}, 2: {"comments": 25}},
        "now": NOW,
        "prior_event_exists": False,
    }
    values.update(changes)
    return build_score_input(**values)


def test_build_score_input_uses_all_six_real_quality_signals() -> None:
    result = build()

    assert result.ai_relevance == 90
    assert result.source_coverage == 70
    assert result.source_authority == 90
    assert result.recency == 100
    assert result.engagement_velocity == round(25 * log10(1 + 145))
    assert result.novelty == 100
    assert "ai_relevance_range:min=80:max=100" in result.reasons


def test_quality_inputs_contains_only_bounded_numeric_rule_inputs() -> None:
    inputs = QualityInputs(
        relevance_scores=(100.0, 80.0),
        independent_root_count=2,
        authority_scores=(100.0, 80.0),
        age_hours=2.0,
        engagement_values=(120.0, 25.0),
        prior_event_exists=False,
        new_independent_root_count=0,
    )

    assert inputs.independent_root_count == 2
    assert inputs.engagement_values == (120.0, 25.0)


def test_independent_roots_are_deduplicated_for_coverage_and_authority() -> None:
    result = build(
        evidence=(root(1, "same-root"), root(2, "same-root")),
        authority_by_item={1: 5, 2: 1},
    )

    assert result.source_coverage == 35
    assert result.source_authority == 100


def test_non_independent_root_does_not_increase_coverage_or_authority() -> None:
    result = build(
        evidence=(root(1, "independent"), root(2, "echo", independent=False)),
        authority_by_item={1: 4, 2: 5},
    )

    assert result.source_coverage == 35
    assert result.source_authority == 80


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(hours=6), 100),
        (timedelta(hours=12), 80),
        (timedelta(hours=24), 60),
        (timedelta(hours=48), 35),
        (timedelta(hours=72), 15),
        (timedelta(hours=72, seconds=1), 0),
    ],
)
def test_recency_uses_inclusive_snapshot_boundaries(age: timedelta, expected: int) -> None:
    result = build(candidate=quality_candidate(occurred_at=NOW - age))

    assert result.recency == expected


def test_engagement_ignores_negative_non_finite_boolean_and_non_numeric_values() -> None:
    result = build(
        engagement_by_item={
            1: {"negative": -2, "nan": float("nan"), "infinite": float("inf")},
            2: {"boolean": True, "text": "500", "timestamp": 500},
        }
    )

    assert result.engagement_velocity == 0
    assert "engagement_unavailable" in result.reasons


def test_engagement_is_capped_at_100() -> None:
    result = build(
        engagement_by_item={
            1: {"views": float("1.7976931348623157e308")},
            2: {"views": float("1.7976931348623157e308")},
        }
    )

    assert result.engagement_velocity == 100


def test_novelty_distinguishes_new_root_from_pure_repeat() -> None:
    new_root = build(
        prior_event_exists=True,
        prior_evidence_roots=frozenset({"official:orion"}),
    )
    pure_repeat = build(
        evidence=(root(1, "official:orion", EvidenceRole.OFFICIAL),),
        prior_event_exists=True,
        prior_evidence_roots=frozenset({"official:orion"}),
    )

    assert new_root.novelty == 50
    assert pure_repeat.novelty == 0


def test_prior_event_without_explicit_new_root_is_a_pure_repeat() -> None:
    assert build(prior_event_exists=True).novelty == 0
