from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import OperationAttemptRecord, OperationEventRecord, OperationRunRecord
from newsradar.operations.retry_policy import is_retryable_error


@dataclass(frozen=True, slots=True)
class OperationRow:
    operation_id: int
    operation_type: str
    status: str
    source_id: str | None
    progress_current: int
    progress_total: int | None
    created_at: datetime
    error_code: str | None
    error_message: str | None
    retry_allowed: bool


@dataclass(frozen=True, slots=True)
class OperationDetail:
    operation: OperationRow
    requested_scope: dict[str, object]
    attempts: tuple[OperationAttemptRecord, ...]
    events: tuple[OperationEventRecord, ...]
    wave_metrics: HighValueWaveMetricsView | None = None


@dataclass(frozen=True, slots=True)
class HighValueWaveMetricsView:
    member_total: int
    evidence_capable_members: int
    direct_evidence_fetch_succeeded: int
    events_with_official_root: int
    events_with_one_professional_root: int
    events_with_two_professional_roots: int
    confirmed_event_count: int
    ambiguous_pairs_checked: int
    model_pair_fallback_count: int


class OperationQueryService:
    def __init__(self, session: Session):
        self.session = session

    def list_recent(self, limit: int = 100) -> tuple[OperationRow, ...]:
        records = self.session.scalars(
            select(OperationRunRecord)
            .order_by(OperationRunRecord.id.desc())
            .limit(limit)
        ).all()
        return tuple(
            self._row(record)
            for record in records
        )

    def get(self, operation_id: int) -> OperationDetail | None:
        record = self.session.get(OperationRunRecord, operation_id)
        if record is None:
            return None
        attempts = tuple(
            self.session.scalars(
                select(OperationAttemptRecord)
                .where(OperationAttemptRecord.operation_run_id == operation_id)
                .order_by(OperationAttemptRecord.attempt_number.desc())
            )
        )
        events = tuple(
            self.session.scalars(
                select(OperationEventRecord)
                .where(OperationEventRecord.operation_run_id == operation_id)
                .order_by(OperationEventRecord.created_at.desc(), OperationEventRecord.id.desc())
                .limit(100)
            )
        )
        return OperationDetail(
            operation=self._row(record),
            requested_scope=dict(record.requested_scope),
            attempts=attempts,
            events=events,
            wave_metrics=(
                _wave_metrics(record.result_summary)
                if record.operation_type == "high_value_news_wave"
                else None
            ),
        )

    @staticmethod
    def _row(record: OperationRunRecord) -> OperationRow:
        return OperationRow(
            operation_id=record.id,
            operation_type=record.operation_type,
            status=record.status,
            source_id=record.requested_scope.get("source_id"),
            progress_current=record.progress_current,
            progress_total=record.progress_total,
            created_at=record.created_at,
            error_code=record.error_code,
            error_message=record.error_message,
            retry_allowed=is_retryable_error(record.error_code),
        )


def _wave_metrics(value: object) -> HighValueWaveMetricsView:
    summary = value if isinstance(value, dict) else {}
    return HighValueWaveMetricsView(
        member_total=_safe_count(summary.get("member_total")),
        evidence_capable_members=_safe_count(summary.get("evidence_capable_members")),
        direct_evidence_fetch_succeeded=_safe_count(
            summary.get("direct_evidence_fetch_succeeded")
        ),
        events_with_official_root=_safe_count(summary.get("events_with_official_root")),
        events_with_one_professional_root=_safe_count(
            summary.get("events_with_one_professional_root")
        ),
        events_with_two_professional_roots=_safe_count(
            summary.get("events_with_two_professional_roots")
        ),
        confirmed_event_count=_safe_count(summary.get("confirmed_event_count")),
        ambiguous_pairs_checked=_safe_count(summary.get("ambiguous_pairs_checked")),
        model_pair_fallback_count=_safe_count(summary.get("model_pair_fallback_count")),
    )


def _safe_count(value: object) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )
