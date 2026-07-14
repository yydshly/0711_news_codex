from __future__ import annotations

from newsradar.events.schema import (
    CandidateCluster,
    ClusterItem,
    EventScoreInput,
    EventStatus,
    EvidenceAssessment,
    EvidenceRole,
)
from newsradar.events.scoring import SCORE_RULE_VERSION, decide_publication, score_event


def full_score_input() -> EventScoreInput:
    return EventScoreInput(
        ai_relevance=100,
        source_coverage=90,
        source_authority=95,
        recency=90,
        engagement_velocity=80,
        novelty=80,
        evidence=(
            EvidenceAssessment(
                raw_item_id=1,
                role=EvidenceRole.OFFICIAL,
                root_evidence_key="official:release",
                independent=True,
            ),
        ),
    )


def candidate_with_roles(*roles: EvidenceRole, disputed: bool = False) -> CandidateCluster:
    return CandidateCluster(
        candidate_key="release",
        items=tuple(
            ClusterItem(raw_item_id=index, evidence_role=role)
            for index, role in enumerate(roles, start=1)
        ),
        metadata={"disputed": disputed},
    )


def assessment(
    role: EvidenceRole, root: str, *, independent: bool = True
) -> EvidenceAssessment:
    return EvidenceAssessment(
        role=role,
        root_evidence_key=root,
        independent=independent,
    )


def test_importance_uses_versioned_weights() -> None:
    score = score_event(full_score_input())

    assert score.importance == 92
    assert score.rule_version == SCORE_RULE_VERSION == "score-v2"


def test_score_preserves_quality_input_reasons() -> None:
    score_input = full_score_input().model_copy(
        update={"reasons": ("engagement_unavailable",)}
    )

    assert "engagement_unavailable" in score_event(score_input).reasons


def test_social_only_candidate_is_emerging_not_confirmed() -> None:
    decision = decide_publication(
        candidate_with_roles(EvidenceRole.SOCIAL, EvidenceRole.COMMUNITY)
    )

    assert decision.status is EventStatus.EMERGING
    assert decision.publish_to_top is False


def test_official_source_confirms_candidate() -> None:
    decision = decide_publication(
        candidate_with_roles(EvidenceRole.OFFICIAL),
        (assessment(EvidenceRole.OFFICIAL, "official:release"),),
    )

    assert decision.status is EventStatus.CONFIRMED
    assert decision.publish_to_top is True
    assert "official_evidence" in decision.reasons


def test_two_independent_professional_roots_confirm_candidate() -> None:
    decision = decide_publication(
        candidate_with_roles(EvidenceRole.PROFESSIONAL_MEDIA, EvidenceRole.PROFESSIONAL_MEDIA),
        (
            assessment(EvidenceRole.PROFESSIONAL_MEDIA, "news:a"),
            assessment(EvidenceRole.PROFESSIONAL_MEDIA, "news:b"),
        ),
    )

    assert decision.status is EventStatus.CONFIRMED
    assert "two_independent_professional_roots" in decision.reasons


def test_aggregated_coverage_does_not_duplicate_professional_root() -> None:
    decision = decide_publication(
        candidate_with_roles(EvidenceRole.PROFESSIONAL_MEDIA, EvidenceRole.AGGREGATOR),
        (
            assessment(EvidenceRole.PROFESSIONAL_MEDIA, "news:a"),
            assessment(EvidenceRole.AGGREGATOR, "news:a", independent=False),
        ),
    )

    assert decision.status is EventStatus.EMERGING
    assert "insufficient_independent_evidence" in decision.reasons


def test_official_evidence_wins_when_same_root_has_conflicting_roles() -> None:
    decision = decide_publication(
        candidate_with_roles(EvidenceRole.PROFESSIONAL_MEDIA, EvidenceRole.OFFICIAL),
        (
            assessment(EvidenceRole.PROFESSIONAL_MEDIA, "release"),
            assessment(EvidenceRole.OFFICIAL, "release"),
        ),
    )

    assert decision.status is EventStatus.CONFIRMED
    assert "official_evidence" in decision.reasons


def test_disputed_candidate_is_explicitly_disputed() -> None:
    decision = decide_publication(candidate_with_roles(EvidenceRole.OFFICIAL, disputed=True))

    assert decision.status is EventStatus.DISPUTED
    assert decision.publish_to_top is False
    assert "conflicting_assertions" in decision.reasons
