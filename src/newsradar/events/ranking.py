"""Deterministic event display ranking and tier decisions."""

from __future__ import annotations

from newsradar.events.schema import (
    CandidateCluster,
    EventTier,
    EvidenceAssessment,
    EvidenceRole,
    ScoreBreakdown,
    TierDecision,
)


def rank_event(score: ScoreBreakdown) -> float:
    """Rank a frozen score snapshot without model or wall-clock inputs."""
    value = (
        0.40 * score.credibility
        + 0.20 * score.importance
        + 0.15 * score.recency
        + 0.15 * score.source_coverage
        + 0.10 * score.engagement_velocity
    )
    return round(max(0.0, min(100.0, value)), 1)


def decide_event_tier(
    candidate: CandidateCluster,
    score: ScoreBreakdown,
    evidence: tuple[EvidenceAssessment, ...],
) -> TierDecision:
    """Classify reader display without allowing social or preprint evidence to confirm."""
    rank_score = rank_event(score)
    if candidate.state == "rejected" or score.ai_relevance < 70:
        return TierDecision(
            tier=EventTier.AUDIT_ONLY,
            rank_score=rank_score,
            reasons=("insufficient_event_quality",),
        )
    roots = {
        assessment.root_evidence_key or f"item:{assessment.raw_item_id}": assessment.role
        for assessment in evidence
        if assessment.independent
    }
    if any(role is EvidenceRole.OFFICIAL for role in roots.values()):
        return TierDecision(
            tier=EventTier.HOTSPOT,
            rank_score=rank_score,
            reasons=("official_independent_root",),
        )
    professional_roots = sum(
        role is EvidenceRole.PROFESSIONAL_MEDIA for role in roots.values()
    )
    if professional_roots >= 2:
        return TierDecision(
            tier=EventTier.HOTSPOT,
            rank_score=rank_score,
            reasons=("two_independent_professional_roots",),
        )
    if any(role is EvidenceRole.RESEARCH for role in roots.values()):
        return TierDecision(
            tier=EventTier.SIGNAL,
            rank_score=rank_score,
            reasons=("preprint_not_peer_reviewed",),
        )
    return TierDecision(
        tier=EventTier.SIGNAL,
        rank_score=rank_score,
        reasons=("evidence_not_yet_sufficient_for_hotspot",),
    )
