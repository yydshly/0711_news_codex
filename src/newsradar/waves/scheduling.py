"""Manual, side-effect-bounded scheduling decisions for high-value news waves.

This module deliberately does not register an operating-system scheduler.  A caller may
ask whether a frozen profile is due, and may enqueue exactly one durable operation.
Neither action performs source or model network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from newsradar.waves.planning import WavePlan
from newsradar.waves.schema import WaveProfile

DEFAULT_WAVE_INTERVAL = timedelta(minutes=30)
_ACTIVE_STATUSES = frozenset({"queued", "running"})


@dataclass(frozen=True, slots=True)
class DueDecision:
    due: bool
    reason: str
    next_due_at: datetime | None


@dataclass(frozen=True, slots=True)
class EnqueueDueResult:
    operation_id: int | None
    reason: str
    next_due_at: datetime | None


class WaveDueCommands(Protocol):
    def latest_high_value_wave(self, profile_id: str): ...

    def enqueue_high_value_wave(self, *, plan: WavePlan, trigger: str) -> int: ...


def wave_due(
    profile: WaveProfile | object,
    latest_operation: object | None,
    *,
    now: datetime,
    interval: timedelta = DEFAULT_WAVE_INTERVAL,
) -> DueDecision:
    """Return a deterministic due decision without mutating the queue.

    An active run always wins.  A terminal run remains protected for one interval so
    a repeatedly-clicked manual command cannot create a burst of equivalent waves.
    """
    del profile  # Profile identity is selected by the caller; cadence is global in v1.5.
    current = _aware_utc(now)
    if latest_operation is None:
        return DueDecision(True, "due", current)
    status = str(getattr(latest_operation, "status", ""))
    created_at = _as_utc(getattr(latest_operation, "created_at", None))
    if status in _ACTIVE_STATUSES:
        return DueDecision(False, "active_or_recent_wave", None)
    if created_at is None:
        return DueDecision(False, "invalid_latest_wave", None)
    next_due_at = created_at + interval
    if current < next_due_at:
        return DueDecision(False, "active_or_recent_wave", next_due_at)
    return DueDecision(True, "due", next_due_at)


def enqueue_due(
    commands: WaveDueCommands,
    plan: WavePlan,
    *,
    now: datetime,
    trigger: str = "enqueue_due",
) -> EnqueueDueResult:
    """Enqueue once if due; the command boundary owns persistence and locking."""
    latest = commands.latest_high_value_wave(plan.profile_id)
    decision = wave_due(plan, latest, now=now)
    if not decision.due:
        return EnqueueDueResult(None, decision.reason, decision.next_due_at)
    try:
        operation_id = commands.enqueue_high_value_wave(plan=plan, trigger=trigger)
    except ValueError as exc:
        # A concurrent web/CLI request can win after the read above.  Preserve its
        # idempotent result instead of retrying, probing, or issuing network calls.
        if str(exc) == "active_high_value_wave_exists":
            return EnqueueDueResult(None, "active_or_recent_wave", None)
        raise
    return EnqueueDueResult(operation_id, "due", decision.next_due_at)


def _as_utc(value: object) -> datetime | None:
    return _aware_utc(value) if isinstance(value, datetime) else None


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
