"""Pure construction of auditable score-v2 inputs from bounded local facts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite, log10
from numbers import Real

from newsradar.events.schema import CandidateCluster, EventScoreInput, EvidenceAssessment

_ENGAGEMENT_FIELDS = frozenset(
    {
        "comments",
        "favourites",
        "favorites",
        "likes",
        "plays",
        "points",
        "reblogs",
        "replies",
        "reposts",
        "retweets",
        "score",
        "shares",
        "stargazers_count",
        "upvotes",
        "views",
    }
)


@dataclass(frozen=True, slots=True)
class QualityInputs:
    """Safe numeric facts consumed by the score-v2 formulas."""

    relevance_scores: tuple[float, ...]
    independent_root_count: int
    authority_scores: tuple[float, ...]
    age_hours: float
    engagement_values: tuple[float, ...]
    prior_event_exists: bool
    new_independent_root_count: int


def build_score_input(
    *,
    candidate: CandidateCluster,
    evidence: tuple[EvidenceAssessment, ...],
    relevance_by_item: Mapping[int, object],
    authority_by_item: Mapping[int, object],
    engagement_by_item: Mapping[int, Mapping[str, object]],
    now: datetime,
    prior_event_exists: bool,
    prior_evidence_roots: frozenset[str] | None = None,
) -> EventScoreInput:
    """Build the six score components without reading payloads, clocks, or external state."""
    member_ids = candidate.raw_item_ids or tuple(item.raw_item_id for item in candidate.items)
    relevance_scores = tuple(
        _bounded_number(relevance_by_item.get(raw_item_id), upper=100)
        for raw_item_id in member_ids
    )
    independent_roots = _independent_roots(evidence)
    authority_scores = tuple(
        max(
            (
                _authority_score(authority_by_item.get(raw_item_id))
                for raw_item_id in raw_item_ids
            ),
            default=0.0,
        )
        for _, raw_item_ids in sorted(independent_roots.items())
    )
    engagement_values = tuple(
        value
        for raw_item_id in sorted(set(member_ids))
        for key, raw_value in sorted(engagement_by_item.get(raw_item_id, {}).items())
        if _is_engagement_field(key)
        and (value := _engagement_value(raw_value)) is not None
    )
    occurred_at = candidate.occurred_at or min(
        (item.published_at for item in candidate.items if item.published_at is not None),
        default=None,
    )
    age_hours = _age_hours(now, occurred_at)
    new_root_count = (
        len(set(independent_roots) - set(prior_evidence_roots))
        if prior_evidence_roots is not None
        else 0
    )
    inputs = QualityInputs(
        relevance_scores=relevance_scores,
        independent_root_count=len(independent_roots),
        authority_scores=authority_scores,
        age_hours=age_hours,
        engagement_values=engagement_values,
        prior_event_exists=prior_event_exists,
        new_independent_root_count=new_root_count,
    )
    return _score_input(inputs, evidence)


def _score_input(
    inputs: QualityInputs, evidence: tuple[EvidenceAssessment, ...]
) -> EventScoreInput:
    relevance = (
        round(sum(inputs.relevance_scores) / len(inputs.relevance_scores))
        if inputs.relevance_scores
        else 0
    )
    coverage = {0: 0, 1: 35, 2: 70}.get(inputs.independent_root_count, 100)
    authority = (
        round(sum(inputs.authority_scores) / len(inputs.authority_scores))
        if inputs.authority_scores
        else 0
    )
    engagement_total = sum(inputs.engagement_values)
    engagement = (
        100
        if not isfinite(engagement_total)
        else min(100, round(25 * log10(1 + engagement_total)))
    )
    if not inputs.prior_event_exists:
        novelty = 100
        novelty_reason = "novelty:no_prior_event"
    elif inputs.new_independent_root_count:
        novelty = 50
        novelty_reason = "novelty:new_independent_evidence"
    else:
        novelty = 0
        novelty_reason = "novelty:pure_repeat"
    relevance_range = (
        f"ai_relevance_range:min={_display(min(inputs.relevance_scores))}:"
        f"max={_display(max(inputs.relevance_scores))}"
        if inputs.relevance_scores
        else "ai_relevance_unavailable"
    )
    engagement_reason = (
        "engagement:log_normalized"
        if inputs.engagement_values
        else "engagement_unavailable"
    )
    return EventScoreInput(
        ai_relevance=relevance,
        source_coverage=coverage,
        source_authority=authority,
        recency=_recency(inputs.age_hours),
        engagement_velocity=engagement,
        novelty=novelty,
        evidence=evidence,
        reasons=(
            relevance_range,
            f"source_coverage:independent_roots={inputs.independent_root_count}",
            "source_authority:independent_root_average",
            f"recency:age_hours={_display(inputs.age_hours)}",
            engagement_reason,
            novelty_reason,
        ),
    )


def _independent_roots(
    evidence: tuple[EvidenceAssessment, ...],
) -> dict[str, tuple[int, ...]]:
    roots: dict[str, set[int]] = {}
    for assessment in evidence:
        if not assessment.independent:
            continue
        root = assessment.root_evidence_key or f"item:{assessment.raw_item_id}"
        raw_item_ids = roots.setdefault(root, set())
        if assessment.raw_item_id is not None:
            raw_item_ids.add(assessment.raw_item_id)
    return {root: tuple(sorted(raw_item_ids)) for root, raw_item_ids in roots.items()}


def _bounded_number(value: object, *, upper: float) -> float:
    number = _finite_number(value)
    if number is None:
        return 0.0
    return min(upper, max(0.0, number))


def _authority_score(value: object) -> float:
    return _bounded_number(value, upper=5) * 20


def _engagement_value(value: object) -> float | None:
    number = _finite_number(value)
    return number if number is not None and number >= 0 else None


def _is_engagement_field(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.casefold().replace("-", "_").replace(" ", "_")
    return normalized in _ENGAGEMENT_FIELDS or normalized.endswith("_count")


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _age_hours(now: datetime, occurred_at: datetime | None) -> float:
    if occurred_at is None:
        return 1_000_000.0
    normalized_now = _aware_utc(now)
    normalized_occurred = _aware_utc(occurred_at)
    return max(0.0, (normalized_now - normalized_occurred).total_seconds() / 3_600)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _recency(age_hours: float) -> int:
    for upper, score in ((6, 100), (12, 80), (24, 60), (48, 35), (72, 15)):
        if age_hours <= upper:
            return score
    return 0


def _display(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:.3f}".rstrip("0").rstrip(".")
