from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from newsradar.daily_reports.autopilot import (
    DailyAutopilotStage,
    serialize_catalog_plan,
)
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
