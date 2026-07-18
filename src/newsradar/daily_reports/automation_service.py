from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session

from newsradar.daily_reports.automation_repository import DailyAutomationRepository
from newsradar.operations.commands import OperationCommandService
from newsradar.waves.local_plan import build_local_wave_plan
from newsradar.waves.planning import WavePlan


@dataclass(frozen=True, slots=True)
class DailyAutomationTickResult:
    outcome: Literal["disabled", "not_due", "enqueued", "reused"]
    run_id: int | None = None


class DailyAutomationService:
    """Enqueue at most one due daily-autopilot run without performing automation work."""

    def __init__(
        self,
        session: Session,
        *,
        utcnow: Callable[[], datetime] | None = None,
        plan_factory: Callable[[Session, int], WavePlan] | None = None,
    ) -> None:
        self.session = session
        self._utcnow = utcnow or (lambda: datetime.now(UTC))
        self._plan_factory = plan_factory or (
            lambda current_session, hours: build_local_wave_plan(
                current_session, window_hours=hours
            )
        )

    def tick(self) -> DailyAutomationTickResult:
        repository = DailyAutomationRepository(self.session, utcnow=self._utcnow)
        try:
            due = repository.lock_due()
            if due is None:
                config = repository.get_or_create()
                self.session.commit()
                return DailyAutomationTickResult("disabled" if not config.enabled else "not_due")

            commands = OperationCommandService(self.session, utcnow=self._utcnow)
            result = commands._enqueue_daily_autopilot_result_in_transaction(
                plan=self._plan_factory(self.session, 24),
                trigger="schedule",
            )
            repository.mark_scheduled(due, run_id=result.run_id)
            self.session.commit()
            return DailyAutomationTickResult(
                "enqueued" if result.created else "reused", result.run_id
            )
        except Exception:
            self.session.rollback()
            raise
