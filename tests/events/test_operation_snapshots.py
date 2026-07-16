from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    HighValueWaveMemberRecord,
    OperationRunRecord,
)
from newsradar.events.operation_snapshots import (
    EventVersionRef,
    event_snapshot_by_id,
    latest_complete_event_snapshot,
)
from newsradar.events.reporting import build_event_quality_report_view
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS

NOW = datetime(2026, 7, 15, 6, 0, tzinfo=UTC)


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _event(session: Session, key: str, version_number: int = 1) -> EventRecord:
    event = EventRecord(
        canonical_key=key,
        status="confirmed",
        occurred_at=NOW,
        current_version_number=version_number,
    )
    session.add(event)
    session.flush()
    session.add_all(
        (
            EventVersionRecord(
                event_id=event.id,
                version_number=version_number,
                payload={},
                created_at=NOW,
            ),
            EventScoreRecord(
                event_id=event.id,
                version_number=version_number,
                heat=50,
                breakdown={},
                created_at=NOW,
            ),
        )
    )
    return event


def _operation(
    session: Session,
    *,
    created_at: datetime,
    refs: list[dict[str, object]],
    status: str = "succeeded",
    algorithm_versions: object | None = None,
) -> OperationRunRecord:
    operation = OperationRunRecord(
        operation_type="event_pipeline",
        trigger="manual",
        status=status,
        requested_scope={
            "window_hours": 72,
            "window_end": NOW.isoformat(),
            "algorithm_versions": (
                dict(EVENT_ALGORITHM_VERSIONS)
                if algorithm_versions is None
                else algorithm_versions
            ),
        },
        result_summary={"event_version_snapshots": refs},
        created_at=created_at,
        finished_at=NOW,
    )
    session.add(operation)
    session.flush()
    return operation


def test_latest_complete_snapshot_skips_newer_incomplete_operation() -> None:
    with Session(_engine()) as session:
        complete_event = _event(session, "complete")
        complete_event_id = complete_event.id
        complete = _operation(
            session,
            created_at=NOW - timedelta(minutes=2),
            refs=[{"event_id": complete_event_id, "version_number": 1}],
        )
        _operation(
            session,
            created_at=NOW - timedelta(minutes=1),
            refs=[{"event_id": 999, "version_number": 1}],
        )
        session.commit()

        snapshot = latest_complete_event_snapshot(session, now=NOW)

    assert snapshot is not None
    assert snapshot.operation_id == complete.id
    assert snapshot.skipped_newer_count == 1
    assert snapshot.event_versions == (EventVersionRef(complete_event_id, 1),)


def test_snapshot_rejects_duplicate_boolean_and_old_algorithm_refs() -> None:
    with Session(_engine()) as session:
        event = _event(session, "event")
        old_versions = {**dict(EVENT_ALGORITHM_VERSIONS), "cluster": "cluster-v2"}
        _operation(
            session,
            created_at=NOW - timedelta(minutes=3),
            refs=[
                {"event_id": event.id, "version_number": 1},
                {"event_id": event.id, "version_number": 1},
            ],
        )
        _operation(
            session,
            created_at=NOW - timedelta(minutes=2),
            refs=[{"event_id": True, "version_number": 1}],
        )
        _operation(
            session,
            created_at=NOW - timedelta(minutes=1),
            refs=[{"event_id": event.id, "version_number": 1}],
            algorithm_versions=old_versions,
        )
        session.commit()

        snapshot = latest_complete_event_snapshot(session, now=NOW)

    assert snapshot is None


def test_current_event_algorithm_snapshot_uses_cluster_v3() -> None:
    assert EVENT_ALGORITHM_VERSIONS["cluster"] == "cluster-v3"


def test_snapshot_rejects_future_or_unfinished_operation_and_accepts_empty_manifest() -> None:
    with Session(_engine()) as session:
        _operation(
            session,
            created_at=NOW + timedelta(minutes=1),
            refs=[],
        )
        _operation(
            session,
            created_at=NOW - timedelta(minutes=2),
            refs=[],
            status="running",
        )
        complete = _operation(
            session,
            created_at=NOW - timedelta(minutes=3),
            refs=[],
        )
        session.commit()

        snapshot = latest_complete_event_snapshot(session, now=NOW)

    assert snapshot is not None
    assert snapshot.operation_id == complete.id
    assert snapshot.event_versions == ()


def test_quality_report_uses_same_complete_snapshot_as_selector() -> None:
    with Session(_engine()) as session:
        event = _event(session, "report-event")
        complete = _operation(
            session,
            created_at=NOW - timedelta(minutes=2),
            refs=[{"event_id": event.id, "version_number": 1}],
        )
        _operation(
            session,
            created_at=NOW - timedelta(minutes=1),
            refs=[{"event_id": 999, "version_number": 1}],
        )
        session.commit()

        view = build_event_quality_report_view(session, window_hours=72, now=NOW)

    assert view.latest_operation_id == complete.id


def test_complete_partial_wave_snapshot_requires_terminal_members_and_manifest() -> None:
    """A partial wave is readable only after the event stage sealed its full manifest."""
    with Session(_engine()) as session:
        event = _event(session, "wave-event")
        operation = OperationRunRecord(
            operation_type="high_value_news_wave",
            trigger="manual",
            status="partial",
            requested_scope={
                "window_hours": 24,
                "window_end": NOW.isoformat(),
                "algorithm_versions": dict(EVENT_ALGORITHM_VERSIONS),
            },
            result_summary={
                "member_total": 2,
                "completed_members": 2,
                "event_manifest_complete": True,
                "event_manifest_count": 1,
                "event_version_snapshots": [
                    {"event_id": event.id, "version_number": 1}
                ],
            },
            created_at=NOW - timedelta(minutes=2),
            finished_at=NOW,
        )
        session.add(operation)
        session.flush()
        session.add_all(
            (
                HighValueWaveMemberRecord(
                    operation_run_id=operation.id,
                    source_id="first",
                    provider_id="provider",
                    definition_hash="first",
                    roles_snapshot=[],
                    availability_snapshot="ready",
                    access_kind_snapshot="rss",
                    fetchable=True,
                    state="succeeded",
                ),
                HighValueWaveMemberRecord(
                    operation_run_id=operation.id,
                    source_id="second",
                    provider_id="provider",
                    definition_hash="second",
                    roles_snapshot=[],
                    availability_snapshot="ready",
                    access_kind_snapshot="rss",
                    fetchable=True,
                    state="failed",
                ),
            )
        )
        session.commit()

        assert event_snapshot_by_id(session, operation.id, now=NOW) is not None

        operation.result_summary = {
            **operation.result_summary,
            "completed_members": 1,
        }
        session.commit()
        assert event_snapshot_by_id(session, operation.id, now=NOW) is None
