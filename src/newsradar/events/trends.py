"""Deterministic trend assessment from persisted heat snapshots."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class TrendDirection(StrEnum):
    RISING = "rising"
    SUSTAINED = "sustained"
    COOLING = "cooling"


@dataclass(frozen=True, slots=True)
class HeatSnapshot:
    observed_at: datetime
    heat: int


@dataclass(frozen=True, slots=True)
class TrendAssessment:
    direction: TrendDirection
    delta: int
    current_heat: int
    baseline_heat: int
    snapshot_count: int
    reason: str
    baseline_observed_at: datetime | None = None


def assess_trend(
    current: HeatSnapshot, history: Iterable[HeatSnapshot]
) -> TrendAssessment:
    """Compare a frozen heat score with the newest complete 24-hour snapshot."""
    current_at = _utc(current.observed_at)
    eligible = sorted(
        (
            snapshot
            for snapshot in history
            if current_at - timedelta(days=7)
            <= _utc(snapshot.observed_at)
            <= current_at - timedelta(hours=24)
        ),
        key=lambda snapshot: _utc(snapshot.observed_at),
    )
    if not eligible:
        return TrendAssessment(
            direction=TrendDirection.RISING,
            delta=0,
            current_heat=current.heat,
            baseline_heat=current.heat,
            snapshot_count=0,
            reason="trend:first_snapshot",
        )
    baseline = eligible[-1]
    delta = current.heat - baseline.heat
    direction = (
        TrendDirection.RISING
        if delta >= 10
        else TrendDirection.COOLING
        if delta <= -10
        else TrendDirection.SUSTAINED
    )
    return TrendAssessment(
        direction=direction,
        delta=delta,
        current_heat=current.heat,
        baseline_heat=baseline.heat,
        snapshot_count=len(eligible),
        reason="trend:24h_persisted_snapshot",
        baseline_observed_at=_utc(baseline.observed_at),
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
