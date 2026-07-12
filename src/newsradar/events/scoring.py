"""Transparent, versioned event scoring and evidence publication gates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from newsradar.events.schema import (
    CandidateCluster,
    EventScoreInput,
    EventStatus,
    EvidenceAssessment,
    EvidenceRole,
    PublicationDecision,
    ScoreBreakdown,
)

SCORE_RULE_VERSION = "score-v1"
CONFIRMATION_THRESHOLD = 70
IMPORTANCE_WEIGHTS = {
    "ai_relevance": 0.25,
    "source_coverage": 0.20,
    "source_authority": 0.20,
    "recency": 0.15,
    "engagement_velocity": 0.10,
    "novelty": 0.10,
}


def weighted_importance(parts: Mapping[str, float]) -> int:
    """Return the weighted importance score using the versioned rule weights."""
    return round(sum(parts[name] * weight for name, weight in IMPORTANCE_WEIGHTS.items()))


def score_event(input: EventScoreInput) -> ScoreBreakdown:
    """Score a candidate's importance, credibility, and current heat deterministically."""
    parts = {
        "ai_relevance": input.ai_relevance,
        "source_coverage": input.source_coverage,
        "source_authority": input.source_authority,
        "recency": input.recency,
        "engagement_velocity": input.engagement_velocity,
        "novelty": input.novelty,
    }
    importance = weighted_importance(parts)
    credibility, credibility_reasons = _credibility(input.evidence)
    heat = round(importance * 0.6 + credibility * 0.4)
    return ScoreBreakdown(
        **parts,
        importance=importance,
        credibility=credibility,
        heat=heat,
        rule_version=SCORE_RULE_VERSION,
        reasons=(
            "importance:versioned_weights",
            *credibility_reasons,
            "heat:60_importance_40_credibility",
        ),
    )


def decide_publication(
    candidate: CandidateCluster, evidence: tuple[EvidenceAssessment, ...] | None = None
) -> PublicationDecision:
    """Determine status without letting aggregators or social echoes confirm an event."""
    if _is_disputed(candidate):
        return PublicationDecision(
            status=EventStatus.DISPUTED,
            publish_to_top=False,
            reasons=("conflicting_assertions",),
        )

    assessments = evidence if evidence is not None else _candidate_assessments(candidate)
    roots = _independent_roots(assessments)
    if any(role is EvidenceRole.OFFICIAL for role in roots.values()):
        return PublicationDecision(
            status=EventStatus.CONFIRMED,
            publish_to_top=True,
            reasons=("official_evidence",),
        )
    professional_roots = sum(
        role is EvidenceRole.PROFESSIONAL_MEDIA for role in roots.values()
    )
    if professional_roots >= 2:
        return PublicationDecision(
            status=EventStatus.CONFIRMED,
            publish_to_top=True,
            reasons=("two_independent_professional_roots",),
        )
    return PublicationDecision(
        status=EventStatus.EMERGING,
        publish_to_top=False,
        reasons=("insufficient_independent_evidence",),
    )


def _credibility(evidence: Iterable[EvidenceAssessment]) -> tuple[int, tuple[str, ...]]:
    roots = _independent_roots(evidence)
    if any(role is EvidenceRole.OFFICIAL for role in roots.values()):
        return 90, ("credibility:official_evidence",)
    professional_roots = sum(
        role is EvidenceRole.PROFESSIONAL_MEDIA for role in roots.values()
    )
    if professional_roots >= 2:
        return 80, ("credibility:two_independent_professional_roots",)
    if professional_roots == 1:
        return 60, ("credibility:one_independent_professional_root",)
    if any(role is EvidenceRole.RESEARCH for role in roots.values()):
        return 65, ("credibility:independent_research",)
    return 35, ("credibility:social_or_community_only_cap",)


def _independent_roots(evidence: Iterable[EvidenceAssessment]) -> dict[str, EvidenceRole]:
    roots: dict[str, EvidenceRole] = {}
    for assessment in evidence:
        if not assessment.independent:
            continue
        root = assessment.root_evidence_key or f"item:{assessment.raw_item_id}"
        current = roots.get(root)
        if current is None or _role_priority(assessment.role) > _role_priority(current):
            roots[root] = assessment.role
    return roots


def _role_priority(role: EvidenceRole) -> int:
    return {
        EvidenceRole.OFFICIAL: 3,
        EvidenceRole.PROFESSIONAL_MEDIA: 2,
        EvidenceRole.RESEARCH: 1,
    }.get(role, 0)


def _candidate_assessments(candidate: CandidateCluster) -> tuple[EvidenceAssessment, ...]:
    return tuple(
        EvidenceAssessment(
            raw_item_id=item.raw_item_id,
            role=item.evidence_role or EvidenceRole.COMMUNITY,
            root_evidence_key=item.canonical_url or f"item:{item.raw_item_id}",
            independent=(
                item.evidence_role
                in {
                    EvidenceRole.OFFICIAL,
                    EvidenceRole.PROFESSIONAL_MEDIA,
                    EvidenceRole.RESEARCH,
                }
            ),
        )
        for item in candidate.items
    )


def _is_disputed(candidate: CandidateCluster) -> bool:
    return bool(candidate.metadata.get("disputed")) or any(
        "conflict" in reason for reason in candidate.reasons
    )
