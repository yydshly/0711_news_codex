from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from newsradar.daily_reports import autopilot_runtime
from newsradar.daily_reports.autopilot import DailyAutopilotStage, serialize_catalog_plan
from newsradar.daily_reports.autopilot_repository import DailyAutopilotRepository
from newsradar.daily_reports.autopilot_runtime import DailyAutopilotHandler
from newsradar.db.models import Base, OperationRunRecord
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.sources.catalog_refresh import (
    CatalogRefreshLane,
    CatalogRefreshMemberSnapshot,
    CatalogRefreshPlan,
)


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(engine)


def _catalog_plan() -> CatalogRefreshPlan:
    return CatalogRefreshPlan.from_members(
        [
            CatalogRefreshMemberSnapshot(
                source_id="source-a",
                provider_id="provider-a",
                definition_hash="source-hash",
                availability="ready",
                coverage_mode="direct",
                access_kind="rss",
                lane=CatalogRefreshLane.CONTENT,
            )
        ]
    )


def _lease(run_id: int, stage: DailyAutopilotStage) -> OperationLease:
    return OperationLease(
        operation_id=1,
        attempt_id=1,
        attempt_number=1,
        worker_id="worker",
        operation_type=OperationType.DAILY_AUTOPILOT.value,
        requested_scope={"daily_autopilot_run_id": run_id, "stage": stage.value},
    )


def test_source_stage_enqueues_refresh_and_delayed_wait() -> None:
    factory = _session_factory()
    with factory() as db:
        run = DailyAutopilotRepository(
            db, utcnow=lambda: datetime(2026, 7, 18, tzinfo=UTC)
        ).create_run(
            window_hours=24,
            trigger="web",
            requested_scope={"catalog_plan": serialize_catalog_plan(_catalog_plan())},
        )
        db.commit()
        run_id = run.id

    result = DailyAutopilotHandler.production([], [], factory)(
        _lease(run_id, DailyAutopilotStage.ENQUEUE_SOURCE_REFRESH), lambda _boundary: None
    )

    with factory() as db:
        saved = DailyAutopilotRepository(db).get(run_id)
        assert result.status is OperationStatus.SUCCEEDED
        assert saved.source_operation_id is not None
        assert saved.stage == DailyAutopilotStage.WAIT_SOURCE_REFRESH.value
        child = db.get(OperationRunRecord, saved.source_operation_id)
        assert child is not None and child.operation_type == "source_catalog_refresh"


def test_partial_source_wait_advances_to_event_enqueue() -> None:
    factory = _session_factory()
    with factory() as db:
        run = DailyAutopilotRepository(db).create_run(
            window_hours=24,
            trigger="web",
            requested_scope={"catalog_plan": serialize_catalog_plan(_catalog_plan())},
        )
        child = OperationRunRecord(
            operation_type=OperationType.SOURCE_CATALOG_REFRESH.value,
            trigger="test",
            status=OperationStatus.PARTIAL.value,
            requested_scope={},
            result_summary={},
            attempt_count=1,
        )
        db.add(child)
        db.flush()
        DailyAutopilotRepository(db).transition(
            run.id,
            stage=DailyAutopilotStage.WAIT_SOURCE_REFRESH,
            source_operation_id=child.id,
        )
        db.commit()
        run_id = run.id

    result = DailyAutopilotHandler.production([], [], factory)(
        _lease(run_id, DailyAutopilotStage.WAIT_SOURCE_REFRESH), lambda _boundary: None
    )

    with factory() as db:
        saved = DailyAutopilotRepository(db).get(run_id)
        assert result.status is OperationStatus.SUCCEEDED
        assert saved.stage == DailyAutopilotStage.ENQUEUE_EVENT_PIPELINE.value


def test_generate_report_reads_identifier_before_closing_its_session(monkeypatch) -> None:
    class GuardedSession:
        active = False

        def __enter__(self):
            self.active = True
            return self

        def __exit__(self, *_args) -> None:
            self.active = False

    class GeneratedReport:
        def __init__(self, session: GuardedSession) -> None:
            self._session = session

        @property
        def id(self) -> int:
            if not self._session.active:
                raise RuntimeError("detached_daily_report")
            return 41

    class ReportService:
        def __init__(self, session: GuardedSession, **_kwargs) -> None:
            self._session = session

        def generate(self, _window_hours: int) -> GeneratedReport:
            return GeneratedReport(self._session)

    session = GuardedSession()
    handler = DailyAutopilotHandler(lambda: session)
    transitions: list[tuple[int, DailyAutopilotStage, dict[str, int]]] = []
    monkeypatch.setattr(autopilot_runtime, "DailyReportService", ReportService)
    monkeypatch.setattr(
        handler,
        "_transition_and_continue",
        lambda run_id, stage, **ids: transitions.append((run_id, stage, ids)),
    )

    result = handler._generate_report(
        SimpleNamespace(id=9, daily_report_id=None, window_hours=24), lambda _boundary: None
    )

    assert result.status is OperationStatus.SUCCEEDED
    assert transitions == [(9, DailyAutopilotStage.WRITE_REVIEWS, {"daily_report_id": 41})]


def test_unexpected_stage_error_marks_autopilot_run_failed(monkeypatch) -> None:
    factory = _session_factory()
    with factory() as db:
        run = DailyAutopilotRepository(db).create_run(
            window_hours=24,
            trigger="web",
            requested_scope={"catalog_plan": serialize_catalog_plan(_catalog_plan())},
        )
        db.commit()
        run_id = run.id

    handler = DailyAutopilotHandler(factory)

    def raise_unexpected(*_args, **_kwargs):
        raise RuntimeError("unexpected_stage_error")

    monkeypatch.setattr(handler, "_advance", raise_unexpected)
    result = handler(
        _lease(run_id, DailyAutopilotStage.ENQUEUE_SOURCE_REFRESH), lambda _boundary: None
    )

    with factory() as db:
        saved = DailyAutopilotRepository(db).get(run_id)
        assert result.status is OperationStatus.SUCCEEDED
        assert saved.status == "failed"
        assert saved.stage == DailyAutopilotStage.FAILED.value
        assert saved.error_code == "daily_autopilot_internal"
