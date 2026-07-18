"""Read-only views for resumable automatic daily-report runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import DailyAutopilotRunRecord, OperationRunRecord


@dataclass(frozen=True, slots=True)
class DailyAutopilotOperationView:
    operation_id: int
    status: str
    progress_current: int
    progress_total: int | None
    error_code: str | None
    error_message: str | None
    result_summary: dict[str, object]


@dataclass(frozen=True, slots=True)
class DailyAutopilotSummaryView:
    run_id: int
    status: str
    stage: str
    window_hours: int
    created_at: datetime
    updated_at: datetime
    daily_report_id: int | None


@dataclass(frozen=True, slots=True)
class DailyAutopilotDetailView(DailyAutopilotSummaryView):
    error_code: str | None
    error_message: str | None
    result_summary: dict[str, object]
    source_operation: DailyAutopilotOperationView | None
    event_operation: DailyAutopilotOperationView | None
    decision_audio_operation: DailyAutopilotOperationView | None
    overview_audio_operation: DailyAutopilotOperationView | None


class DailyAutopilotQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_recent(self, *, limit: int = 10) -> tuple[DailyAutopilotSummaryView, ...]:
        rows = self.session.scalars(
            select(DailyAutopilotRunRecord)
            .order_by(DailyAutopilotRunRecord.created_at.desc(), DailyAutopilotRunRecord.id.desc())
            .limit(max(1, min(limit, 50)))
        )
        return tuple(self._summary(row) for row in rows)

    def detail(self, run_id: int) -> DailyAutopilotDetailView | None:
        row = self.session.get(DailyAutopilotRunRecord, run_id)
        if row is None:
            return None
        return DailyAutopilotDetailView(
            **asdict(self._summary(row)),
            error_code=row.error_code,
            error_message=row.error_message,
            result_summary=dict(row.result_summary),
            source_operation=self._operation(row.source_operation_id),
            event_operation=self._operation(row.event_operation_id),
            decision_audio_operation=self._operation(row.decision_audio_operation_id),
            overview_audio_operation=self._operation(row.overview_audio_operation_id),
        )

    @staticmethod
    def _summary(row: DailyAutopilotRunRecord) -> DailyAutopilotSummaryView:
        return DailyAutopilotSummaryView(
            run_id=row.id,
            status=row.status,
            stage=row.stage,
            window_hours=row.window_hours,
            created_at=row.created_at,
            updated_at=row.updated_at,
            daily_report_id=row.daily_report_id,
        )

    def _operation(self, operation_id: int | None) -> DailyAutopilotOperationView | None:
        if operation_id is None:
            return None
        row = self.session.get(OperationRunRecord, operation_id)
        if row is None:
            return None
        return DailyAutopilotOperationView(
            operation_id=row.id,
            status=row.status,
            progress_current=row.progress_current,
            progress_total=row.progress_total,
            error_code=row.error_code,
            error_message=row.error_message,
            result_summary=(
                dict(row.result_summary) if isinstance(row.result_summary, dict) else {}
            ),
        )
