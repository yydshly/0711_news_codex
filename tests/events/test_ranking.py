from newsradar.events.ranking import decide_event_tier, rank_event
from newsradar.events.schema import (
    CandidateCluster,
    EventTier,
    EvidenceAssessment,
    EvidenceRole,
    ScoreBreakdown,
)


def score_breakdown(**changes: object) -> ScoreBreakdown:
    values = {
        "ai_relevance": 90,
        "source_coverage": 60,
        "source_authority": 80,
        "recency": 70,
        "engagement_velocity": 50,
        "novelty": 60,
        "importance": 80,
        "credibility": 90,
        "heat": 84,
        "rule_version": "score-v2",
        "reasons": (),
    }
    values.update(changes)
    return ScoreBreakdown(**values)


def test_rank_formula_uses_only_deterministic_snapshot() -> None:
    score = score_breakdown(
        credibility=90,
        importance=80,
        recency=70,
        source_coverage=60,
        engagement_velocity=50,
    )

    assert rank_event(score) == 76.5


def test_official_single_root_can_be_hotspot() -> None:
    decision = decide_event_tier(
        CandidateCluster(candidate_key="official", title="OpenAI launches Orion"),
        score_breakdown(),
        (
            EvidenceAssessment(
                role=EvidenceRole.OFFICIAL,
                independent=True,
                root_evidence_key="official:openai",
            ),
        ),
    )

    assert decision.tier is EventTier.HOTSPOT


def test_preprint_stays_signal_without_independent_confirmation() -> None:
    decision = decide_event_tier(
        CandidateCluster(candidate_key="paper", title="New AI benchmark paper"),
        score_breakdown(),
        (
            EvidenceAssessment(
                role=EvidenceRole.RESEARCH,
                independent=True,
                root_evidence_key="arxiv:paper",
            ),
        ),
    )

    assert decision.tier is EventTier.SIGNAL
    assert "preprint_not_peer_reviewed" in decision.reasons


def test_community_velocity_cannot_promote_unconfirmed_event() -> None:
    decision = decide_event_tier(
        CandidateCluster(candidate_key="community", title="Community rumor"),
        score_breakdown(engagement_velocity=100, importance=100, credibility=35),
        (
            EvidenceAssessment(
                role=EvidenceRole.COMMUNITY,
                independent=True,
                root_evidence_key="community:thread",
            ),
        ),
    )

    assert decision.tier is EventTier.SIGNAL
