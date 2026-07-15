from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Event, Lock, Thread
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from newsradar.db.models import Base, HighValueWaveMemberRecord, OperationRunRecord
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS
from newsradar.ingestion.schema import FetchOutcome, FetchResult
from newsradar.ingestion.service import SourceFetchSummary
from newsradar.operations.repository import OperationLease, OperationRepository
from newsradar.operations.schema import OperationType
from newsradar.operations.worker import OperationCancelled
from newsradar.sources.repository import canonical_definition
from newsradar.sources.schema import SourceDefinition
from tests.operations.test_fetch_runtime import _source


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _lease(operation_id: int, attempt_id: int = 1) -> OperationLease:
    return OperationLease(
        operation_id, attempt_id, 1, "worker", {}, OperationType.HIGH_VALUE_NEWS_WAVE
    )


def _freeze(
    db: Session, *sources: SourceDefinition, fetchable: dict[str, bool] | None = None
) -> int:
    operation = OperationRepository(db).enqueue(
        OperationType.HIGH_VALUE_NEWS_WAVE,
        {
            "window_hours": 24,
            "window_end": datetime.now(UTC).isoformat(),
            "algorithm_versions": dict(EVENT_ALGORITHM_VERSIONS),
        },
    )
    for source in sources:
        _, definition_hash = canonical_definition(source)
        db.add(
            HighValueWaveMemberRecord(
                operation_run_id=operation.id,
                source_id=source.id,
                provider_id=source.provider_id,
                definition_hash=definition_hash,
                roles_snapshot=["discovery"],
                availability_snapshot="ready",
                access_kind_snapshot="rss",
                fetchable=(fetchable or {}).get(source.id, True),
                state="pending",
            )
        )
    db.get(OperationRunRecord, operation.id).progress_total = len(sources)
    db.commit()
    return operation.id


def test_wave_fetches_only_claimed_fetchable_members_and_blocks_others() -> None:
    from newsradar.waves.runtime import HighValueWaveHandler

    first, second, blocked = _source("first"), _source("second"), _source("blocked")
    fetched: list[str] = []
    with _session() as db:
        operation_id = _freeze(db, first, second, blocked, fetchable={"blocked": False})

        def execute(source, operation_id, checkpoint, scope):
            fetched.append(source.id)
            return SourceFetchSummary(
                source.id, FetchResult(outcome=FetchOutcome.SUCCEEDED), fetch_run_id=9
            )

        result = HighValueWaveHandler([first, second, blocked], lambda: db, execute)(
            _lease(operation_id), lambda _: None
        )
        members = {member.source_id: member for member in db.query(HighValueWaveMemberRecord)}

        assert fetched == ["first", "second"]
        assert result.result_summary["fetch_succeeded"] == 2
        assert result.result_summary["blocked"] == 1
        assert members["blocked"].state == "blocked"
        assert members["blocked"].conclusion and "冻结" in members["blocked"].conclusion
        assert db.get(OperationRunRecord, operation_id).progress_current == 3


def test_wave_runs_event_stage_after_all_members_reach_terminal_state(monkeypatch) -> None:
    """The frozen wave owns one window and only publishes after its fetch manifest ends."""
    from newsradar.events.pipeline import EventPipeline
    from newsradar.waves.runtime import HighValueWaveHandler

    source = _source("source")
    calls: list[dict[str, object]] = []

    class FakePipeline:
        def run(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                current_event_ids=(41,),
                event_version_snapshots=((41, 2),),
                model_fallback_count=1,
            )

    monkeypatch.setattr(
        EventPipeline,
        "production",
        classmethod(lambda cls, session: FakePipeline()),
    )
    with _session() as db:
        operation_id = _freeze(db, source)
        operation = db.get(OperationRunRecord, operation_id)
        assert operation is not None
        operation.requested_scope = {
            "window_hours": 24,
            "window_end": datetime.now(UTC).isoformat(),
        }
        db.commit()
        lease = OperationLease(
            operation_id,
            1,
            1,
            "worker",
            dict(operation.requested_scope),
            OperationType.HIGH_VALUE_NEWS_WAVE,
        )

        result = HighValueWaveHandler(
            [source],
            lambda: db,
            lambda source, *args: SourceFetchSummary(
                source.id, FetchResult(outcome=FetchOutcome.SUCCEEDED)
            ),
        )(lease, lambda _: None)

    assert len(calls) == 1
    assert calls[0]["operation_id"] == operation_id
    assert calls[0]["window_hours"] == 24
    assert callable(calls[0]["checkpoint"])
    assert result.status.value == "succeeded"
    assert result.result_summary["member_total"] == 1
    assert result.result_summary["completed_members"] == 1
    assert result.result_summary["event_manifest_complete"] is True
    assert result.result_summary["event_version_snapshots"] == [
        {"event_id": 41, "version_number": 2}
    ]
    assert result.result_summary["model_degraded"] is True


def test_stale_definition_finishes_without_network() -> None:
    from newsradar.waves.runtime import HighValueWaveHandler

    frozen = _source("source")
    changed = frozen.model_copy(update={"name": "Changed source"})
    calls: list[str] = []
    with _session() as db:
        operation_id = _freeze(db, frozen)
        handler = HighValueWaveHandler([changed], lambda: db, lambda *args: calls.append("network"))

        result = handler.run_member(operation_id=operation_id, source_id="source", attempt_id=1)

        assert result.result_code == "stale_result"
        assert calls == []
        assert db.query(HighValueWaveMemberRecord).one().state == "stale_result"


def test_claim_failure_performs_no_network_io() -> None:
    from newsradar.waves.runtime import HighValueWaveHandler

    source = _source("source")
    calls: list[str] = []
    with _session() as db:
        operation_id = _freeze(db, source)
        db.query(HighValueWaveMemberRecord).one().state = "running"
        db.commit()
        result = HighValueWaveHandler(
            [source], lambda: db, lambda *args: calls.append("network")
        ).run_member(operation_id=operation_id, source_id="source", attempt_id=1)

        assert result.result_code == "already_claimed"
        assert calls == []


@pytest.mark.parametrize("boundary", ["before_network", "fetch_checkpoint", "after_item"])
def test_wave_propagates_worker_cancellation_from_shared_fetch_callbacks(boundary: str) -> None:
    from newsradar.waves.runtime import HighValueWaveHandler

    source = _source("source")
    with _session() as db:
        operation_id = _freeze(db, source)

        def execute(source, operation_id, checkpoint, scope):
            checkpoint(boundary)
            raise AssertionError("cancellation must leave the executor immediately")

        with pytest.raises(OperationCancelled):
            HighValueWaveHandler([source], lambda: db, execute)(
                _lease(operation_id), lambda _: (_ for _ in ()).throw(OperationCancelled())
            )


def test_deadline_finishes_members_without_entering_event_pipeline(monkeypatch) -> None:
    from newsradar.events.pipeline import EventPipeline
    from newsradar.waves.runtime import HighValueWaveHandler

    first, second = _source("first"), _source("second")
    calls: list[str] = []

    def unexpected_event_pipeline(cls, session):
        del cls, session
        raise AssertionError("expired wave must not build an event manifest")

    monkeypatch.setattr(EventPipeline, "production", classmethod(unexpected_event_pipeline))
    with _session() as db:
        operation_id = _freeze(db, first, second)
        lease = OperationLease(
            operation_id,
            1,
            1,
            "worker",
            {"deadline_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()},
            OperationType.HIGH_VALUE_NEWS_WAVE,
        )
        result = HighValueWaveHandler(
            [first, second],
            lambda: db,
            lambda source, *args: calls.append(source.id),
        )(lease, lambda _: None)

        assert result.status.value == "failed"
        assert result.error_code == "operation_timeout"
        assert result.result_summary["event_manifest_complete"] is False
        assert calls == []
        assert {member.state for member in db.query(HighValueWaveMemberRecord)} == {"timeout"}
        assert db.get(OperationRunRecord, operation_id).progress_current == 2


@pytest.mark.parametrize(
    ("source_count", "provider_count", "expected_limit"), [(7, 7, 6), (3, 1, 2)]
)
def test_wave_applies_global_and_provider_network_limits(
    source_count: int, provider_count: int, expected_limit: int
) -> None:
    from newsradar.waves.runtime import HighValueWaveHandler

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sources = [
        _source(f"source-{index}").model_copy(update={"provider_id": f"p-{index % provider_count}"})
        for index in range(source_count)
    ]
    active = maximum = 0
    lock, started, release = Lock(), Event(), Event()

    def execute(source, operation_id, checkpoint, scope):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            if maximum >= expected_limit:
                started.set()
        assert release.wait(2)
        with lock:
            active -= 1
        return SourceFetchSummary(source.id, FetchResult(outcome=FetchOutcome.SUCCEEDED))

    with Session(engine) as db:
        operation_id = _freeze(db, *sources)
        handler = HighValueWaveHandler(sources, lambda: Session(engine), execute)
        thread = Thread(target=lambda: handler(_lease(operation_id), lambda _: None))
        thread.start()
        assert started.wait(1)
        assert maximum <= expected_limit
        release.set()
        thread.join(3)
        assert not thread.is_alive()


def test_rate_limit_and_member_error_do_not_block_other_wave_members() -> None:
    from newsradar.waves.runtime import HighValueWaveHandler

    limited, broken, good = _source("limited"), _source("broken"), _source("good")
    with _session() as db:
        operation_id = _freeze(db, limited, broken, good)

        def execute(source, operation_id, checkpoint, scope):
            if source.id == "limited":
                return SourceFetchSummary(
                    source.id,
                    FetchResult(
                        outcome=FetchOutcome.FAILED,
                        http_status=429,
                        error_code="rate_limited",
                    ),
                )
            if source.id == "broken":
                raise RuntimeError("isolated")
            return SourceFetchSummary(source.id, FetchResult(outcome=FetchOutcome.SUCCEEDED))

        result = HighValueWaveHandler([limited, broken, good], lambda: db, execute)(
            _lease(operation_id), lambda _: None
        )
        states = {member.source_id: member.state for member in db.query(HighValueWaveMemberRecord)}

        assert result.status.value == "partial"
        assert states == {"limited": "failed", "broken": "failed", "good": "succeeded"}
