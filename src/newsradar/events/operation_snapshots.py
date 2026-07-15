"""Validated immutable event snapshots selected from successful Operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import MappingProxyType

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    EventScoreRecord,
    EventVersionRecord,
    HighValueWaveMemberRecord,
    OperationRunRecord,
)
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS

MAX_SNAPSHOT_EVENTS = 1_000
MAX_WINDOW_HOURS = 720
_MAX_IDENTIFIER = 9_223_372_036_854_775_807


@dataclass(frozen=True, slots=True, order=True)
class EventVersionRef:
    event_id: int
    version_number: int


@dataclass(frozen=True, slots=True)
class OperationSnapshotRef:
    operation_id: int
    window_hours: int
    window_end: datetime
    finished_at: datetime
    algorithm_versions: Mapping[str, str]
    event_versions: tuple[EventVersionRef, ...]
    skipped_newer_count: int = 0


def latest_complete_event_snapshot(
    session: Session,
    *,
    now: datetime | None = None,
    window_hours: int | None = None,
) -> OperationSnapshotRef | None:
    """Return the newest complete immutable event snapshot safe for readers."""
    checked_at = _aware_utc(now or datetime.now(UTC))
    if window_hours is not None and (
        isinstance(window_hours, bool)
        or not isinstance(window_hours, int)
        or not 0 < window_hours <= MAX_WINDOW_HOURS
    ):
        return None
    skipped = 0
    statement = (
        select(OperationRunRecord)
        .where(
            OperationRunRecord.operation_type.in_(("event_pipeline", "high_value_news_wave")),
            OperationRunRecord.status.in_(("succeeded", "partial")),
            OperationRunRecord.created_at <= checked_at,
        )
        .order_by(OperationRunRecord.id.desc())
        .execution_options(yield_per=100)
    )
    for operation in session.scalars(statement):
        snapshot = _validated_snapshot(session, operation, now=checked_at)
        if snapshot is not None and (
            window_hours is None or snapshot.window_hours == window_hours
        ):
            return replace(snapshot, skipped_newer_count=skipped)
        skipped += 1
    return None


def event_snapshot_by_id(
    session: Session,
    operation_id: int,
    *,
    now: datetime | None = None,
) -> OperationSnapshotRef | None:
    """Return one validated Operation snapshot, without falling back to another run."""
    if not _positive_int(operation_id):
        return None
    checked_at = _aware_utc(now or datetime.now(UTC))
    operation = session.get(OperationRunRecord, operation_id)
    if operation is None or _aware_utc(operation.created_at) > checked_at:
        return None
    return _validated_snapshot(session, operation, now=checked_at)


def _validated_snapshot(
    session: Session,
    operation: OperationRunRecord,
    *,
    now: datetime,
) -> OperationSnapshotRef | None:
    scope = operation.requested_scope
    summary = operation.result_summary
    if not _operation_can_publish_snapshot(session, operation):
        return None
    if not isinstance(scope, dict) or not isinstance(summary, dict):
        return None
    window_hours = _positive_int(scope.get("window_hours"))
    window_end = _datetime_from_json(scope.get("window_end"))
    finished_at = _aware_utc(operation.finished_at) if operation.finished_at else None
    if (
        window_hours is None
        or window_hours > MAX_WINDOW_HOURS
        or window_end is None
        or window_end > now
        or finished_at is None
        or finished_at > now
        or scope.get("algorithm_versions") != dict(EVENT_ALGORITHM_VERSIONS)
    ):
        return None
    refs = _event_refs(summary.get("event_version_snapshots"))
    if refs is None or not _version_and_score_records_exist(session, refs, finished_at):
        return None
    return OperationSnapshotRef(
        operation_id=operation.id,
        window_hours=window_hours,
        window_end=window_end,
        finished_at=finished_at,
        algorithm_versions=MappingProxyType(dict(EVENT_ALGORITHM_VERSIONS)),
        event_versions=refs,
    )


def _operation_can_publish_snapshot(session: Session, operation: OperationRunRecord) -> bool:
    """Keep queued, cancelled, and incomplete wave runs out of reader-visible pages."""
    if operation.operation_type == "event_pipeline":
        return operation.status == "succeeded"
    if (
        operation.operation_type != "high_value_news_wave"
        or operation.status not in {"succeeded", "partial"}
        or not isinstance(operation.result_summary, dict)
    ):
        return False
    summary = operation.result_summary
    member_total = _positive_int(summary.get("member_total"))
    completed_members = _positive_int(summary.get("completed_members"))
    if (
        member_total is None
        or completed_members is None
        or member_total != completed_members
        or summary.get("event_manifest_complete") is not True
    ):
        return False
    manifest_count = summary.get("event_manifest_count")
    refs = _event_refs(summary.get("event_version_snapshots"))
    if (
        isinstance(manifest_count, bool)
        or not isinstance(manifest_count, int)
        or manifest_count < 0
        or refs is None
        or manifest_count != len(refs)
    ):
        return False
    members = list(
        session.scalars(
            select(HighValueWaveMemberRecord).where(
                HighValueWaveMemberRecord.operation_run_id == operation.id
            )
        )
    )
    terminal = {"succeeded", "partial", "failed", "blocked", "stale_result", "timeout"}
    return len(members) == member_total and all(member.state in terminal for member in members)


def _event_refs(value: object) -> tuple[EventVersionRef, ...] | None:
    if not isinstance(value, list) or len(value) > MAX_SNAPSHOT_EVENTS:
        return None
    refs: list[EventVersionRef] = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {"event_id", "version_number"}:
            return None
        event_id = _positive_int(row.get("event_id"))
        version_number = _positive_int(row.get("version_number"))
        if event_id is None or version_number is None:
            return None
        refs.append(EventVersionRef(event_id, version_number))
    result = tuple(refs)
    return result if len(set(result)) == len(result) else None


def _version_and_score_records_exist(
    session: Session,
    refs: tuple[EventVersionRef, ...],
    finished_at: datetime,
) -> bool:
    if not refs:
        return True
    event_ids = {ref.event_id for ref in refs}
    expected = set(refs)
    version_refs = {
        EventVersionRef(event_id, version_number)
        for event_id, version_number in session.execute(
            select(EventVersionRecord.event_id, EventVersionRecord.version_number).where(
                EventVersionRecord.event_id.in_(event_ids),
                EventVersionRecord.created_at <= finished_at,
            )
        )
    }
    if not expected.issubset(version_refs):
        return False
    score_refs = {
        EventVersionRef(event_id, version_number)
        for event_id, version_number in session.execute(
            select(EventScoreRecord.event_id, EventScoreRecord.version_number).where(
                EventScoreRecord.event_id.in_(event_ids),
                EventScoreRecord.created_at <= finished_at,
            )
        )
    }
    return expected.issubset(score_refs)


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= _MAX_IDENTIFIER:
        return None
    return value


def _datetime_from_json(value: object) -> datetime | None:
    if not isinstance(value, str) or not 0 < len(value) <= 64:
        return None
    try:
        return _aware_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
