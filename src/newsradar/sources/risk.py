from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from newsradar.sources.probes.base import ProbeOutcome, ProbeResult
from newsradar.sources.schema import SourceDefinition, SourceStatus


class RiskBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    DISABLED = "disabled"


@dataclass(frozen=True)
class RiskDecision:
    score: int
    band: RiskBand
    reason: str


def assess_risk(source: SourceDefinition) -> RiskDecision:
    score = source.total_risk
    if source.risk.hard_block_reason:
        return RiskDecision(score, RiskBand.DISABLED, source.risk.hard_block_reason)
    if score <= 7:
        return RiskDecision(score, RiskBand.LOW, "Low risk; eligible after probe acceptance")
    if score <= 14:
        return RiskDecision(score, RiskBand.MEDIUM, "Medium risk; fallback method required")
    if score <= 19:
        return RiskDecision(score, RiskBand.HIGH, "High risk; discovery-only and optional")
    return RiskDecision(score, RiskBand.DISABLED, "Risk score requires source to remain disabled")


def recommend_status(
    source: SourceDefinition,
    results: list[ProbeResult],
    *,
    now: datetime | None = None,
) -> SourceStatus:
    decision = assess_risk(source)
    if decision.band == RiskBand.DISABLED:
        return SourceStatus.DISABLED
    if decision.band == RiskBand.HIGH:
        return SourceStatus.CANDIDATE
    if not results:
        return SourceStatus.CANDIDATE

    recent = results[-3:]
    if any(result.outcome in {ProbeOutcome.FAILED, ProbeOutcome.BLOCKED} for result in recent):
        return SourceStatus.DEGRADED
    if any(result.field_completeness < 0.9 for result in recent):
        return SourceStatus.DEGRADED
    current = now or datetime.now(UTC)
    freshness_window = max(timedelta(days=30), timedelta(minutes=source.poll_interval_minutes * 3))
    if any(
        result.latest_published_at is None
        or current - result.latest_published_at > freshness_window
        for result in recent
    ):
        return SourceStatus.DEGRADED
    if len(recent) < 3 or any(result.outcome != ProbeOutcome.SUCCESS for result in recent):
        return SourceStatus.CANDIDATE
    if decision.band == RiskBand.MEDIUM and len(source.access_methods) < 2:
        return SourceStatus.CANDIDATE
    return SourceStatus.ACTIVE
