from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime


class OperationTimedOut(TimeoutError):
    """Raised when a durable operation crosses its persisted deadline."""


@dataclass(frozen=True)
class OperationDeadline:
    deadline_at: datetime
    now: Callable[[], datetime]

    @classmethod
    def from_scope(
        cls,
        scope: Mapping[str, object],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> OperationDeadline:
        raw = scope.get("deadline_at")
        if not isinstance(raw, str):
            raise ValueError("operation scope is missing deadline_at")
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("deadline_at must include a timezone")
        return cls(parsed.astimezone(UTC), now or (lambda: datetime.now(UTC)))

    def check(self, boundary: str) -> None:
        if self.remaining_seconds() <= 0:
            raise OperationTimedOut(f"operation deadline exceeded at {boundary}")

    def remaining_seconds(self) -> float:
        return max(0.0, (self.deadline_at - self.now()).total_seconds())
