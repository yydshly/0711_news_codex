from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.daily_reports.autopilot import DailyAutopilotStage
from newsradar.db.models import DailyAutopilotRunRecord


class DailyAutopilotRepository:
    def __init__(
        self,
        session: Session,
        *,
        utcnow: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self._utcnow = utcnow or (lambda: datetime.now(UTC))

    def create_run(
        self,
        *,
        window_hours: int,
        trigger: str,
        requested_scope: dict,
    ) -> DailyAutopilotRunRecord:
        if window_hours not in {24, 48, 72}:
            raise ValueError("invalid_daily_report_window")
        if self.session.scalar(
            select(DailyAutopilotRunRecord.id).where(
                DailyAutopilotRunRecord.status.in_(("queued", "running"))
            )
        ) is not None:
            raise ValueError("active_daily_autopilot_exists")
        run = DailyAutopilotRunRecord(
            trigger=trigger,
            status="queued",
            stage=DailyAutopilotStage.ENQUEUE_SOURCE_REFRESH.value,
            window_hours=window_hours,
            requested_scope=requested_scope,
            result_summary={},
            created_at=self._utcnow(),
            updated_at=self._utcnow(),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def get(self, run_id: int) -> DailyAutopilotRunRecord:
        run = self.session.get(DailyAutopilotRunRecord, run_id)
        if run is None:
            raise LookupError("daily_autopilot_not_found")
        return run

    def get_for_update(self, run_id: int) -> DailyAutopilotRunRecord:
        run = self.session.get(DailyAutopilotRunRecord, run_id, with_for_update=True)
        if run is None:
            raise LookupError("daily_autopilot_not_found")
        return run

    def transition(
        self,
        run_id: int,
        *,
        stage: DailyAutopilotStage,
        status: str | None = None,
        source_operation_id: int | None = None,
        event_operation_id: int | None = None,
        daily_report_id: int | None = None,
        decision_audio_operation_id: int | None = None,
        overview_audio_operation_id: int | None = None,
    ) -> DailyAutopilotRunRecord:
        run = self.get_for_update(run_id)
        run.stage = stage.value
        run.status = status or "running"
        for field, value in (
            ("source_operation_id", source_operation_id),
            ("event_operation_id", event_operation_id),
            ("daily_report_id", daily_report_id),
            ("decision_audio_operation_id", decision_audio_operation_id),
            ("overview_audio_operation_id", overview_audio_operation_id),
        ):
            if value is not None:
                setattr(run, field, value)
        run.updated_at = self._utcnow()
        if run.status in {"succeeded", "failed", "cancelled"}:
            run.finished_at = self._utcnow()
        self.session.flush()
        return run

    def fail(self, run_id: int, code: str, message: str) -> DailyAutopilotRunRecord:
        run = self.transition(
            run_id,
            stage=DailyAutopilotStage.FAILED,
            status="failed",
        )
        run.error_code = code
        run.error_message = message
        self.session.flush()
        return run

    def cancel(self, run_id: int) -> DailyAutopilotRunRecord:
        run = self.get_for_update(run_id)
        if run.status not in {"queued", "running"}:
            return run
        return self.transition(
            run_id,
            stage=DailyAutopilotStage.CANCELLED,
            status="cancelled",
        )
