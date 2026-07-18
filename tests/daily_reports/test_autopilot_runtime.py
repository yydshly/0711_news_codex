from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from newsradar.daily_reports import autopilot_runtime
from newsradar.daily_reports.autopilot import (
    DailyAutopilotStage,
    serialize_catalog_plan,
    serialize_wave_plan,
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
from newsradar.waves.planning import WaveMemberSnapshot, wave_plan_from_members


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


def _wave_plan():
    return wave_plan_from_members(
        profile_id="high-value",
        members=(
            WaveMemberSnapshot(
                "source-a",
                "provider-a",
                "source-hash",
                ("evidence",),
                "ready",
                "rss",
                True,
                None,
            ),
        ),
        window_hours=24,
        trend_days=7,
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
        DailyAutopilotRepository(db).transition(
            run.id, stage=DailyAutopilotStage.ENQUEUE_SOURCE_REFRESH
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
        DailyAutopilotRepository(db).transition(
            run.id, stage=DailyAutopilotStage.ENQUEUE_SOURCE_REFRESH
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


def test_content_stage_enqueues_high_value_wave() -> None:
    factory = _session_factory()
    with factory() as db:
        run = DailyAutopilotRepository(db).create_run(
            window_hours=24,
            trigger="web",
            requested_scope={"wave_plan": serialize_wave_plan(_wave_plan())},
        )
        db.commit()
        run_id = run.id

    result = DailyAutopilotHandler.production([], [], factory)(
        _lease(run_id, DailyAutopilotStage.ENQUEUE_CONTENT_WAVE), lambda _boundary: None
    )

    with factory() as db:
        saved = DailyAutopilotRepository(db).get(run_id)
        child = db.get(OperationRunRecord, saved.event_operation_id)
        assert result.status is OperationStatus.SUCCEEDED
        assert child is not None
        assert child.operation_type == OperationType.HIGH_VALUE_NEWS_WAVE.value
        assert saved.stage == DailyAutopilotStage.WAIT_CONTENT_WAVE.value


def test_content_stage_waits_when_another_wave_is_active() -> None:
    factory = _session_factory()
    with factory() as db:
        run = DailyAutopilotRepository(db).create_run(
            window_hours=24,
            trigger="web",
            requested_scope={"wave_plan": serialize_wave_plan(_wave_plan())},
        )
        db.add(
            OperationRunRecord(
                operation_type=OperationType.HIGH_VALUE_NEWS_WAVE.value,
                trigger="manual",
                status=OperationStatus.RUNNING.value,
                requested_scope={},
                result_summary={},
            )
        )
        db.commit()
        run_id = run.id

    result = DailyAutopilotHandler(factory)(
        _lease(run_id, DailyAutopilotStage.ENQUEUE_CONTENT_WAVE), lambda _boundary: None
    )

    with factory() as db:
        saved = DailyAutopilotRepository(db).get(run_id)
        assert result.result_summary["waiting_for_content_wave"] is True
        assert saved.event_operation_id is None
        assert saved.stage == DailyAutopilotStage.ENQUEUE_CONTENT_WAVE.value


def _run_waiting_for_content_wave(
    factory,
    *,
    status: OperationStatus,
    result_summary: dict[str, object],
    error_code: str | None = None,
    error_message: str | None = None,
) -> tuple[int, int]:
    with factory() as db:
        run = DailyAutopilotRepository(db).create_run(
            window_hours=24,
            trigger="web",
            requested_scope={"wave_plan": serialize_wave_plan(_wave_plan())},
        )
        child = OperationRunRecord(
            operation_type=OperationType.HIGH_VALUE_NEWS_WAVE.value,
            trigger="test",
            status=status.value,
            requested_scope={},
            result_summary=result_summary,
            error_code=error_code,
            error_message=error_message,
            attempt_count=1,
        )
        db.add(child)
        db.flush()
        DailyAutopilotRepository(db).transition(
            run.id,
            stage=DailyAutopilotStage.WAIT_CONTENT_WAVE,
            event_operation_id=child.id,
        )
        db.commit()
        return run.id, child.id


@pytest.mark.parametrize("status", [OperationStatus.SUCCEEDED, OperationStatus.PARTIAL])
def test_complete_content_wave_with_events_advances_to_report(status: OperationStatus) -> None:
    factory = _session_factory()
    run_id, _child_id = _run_waiting_for_content_wave(
        factory,
        status=status,
        result_summary={
            "fetch_succeeded": 3,
            "event_manifest_complete": True,
            "event_manifest_count": 2,
        },
    )

    DailyAutopilotHandler(factory)(
        _lease(run_id, DailyAutopilotStage.WAIT_CONTENT_WAVE), lambda _boundary: None
    )

    with factory() as db:
        saved = DailyAutopilotRepository(db).get(run_id)
        assert saved.stage == DailyAutopilotStage.GENERATE_REPORT.value
        assert saved.status == "running"


def test_content_wave_with_real_fetches_and_empty_manifest_completes_no_content() -> None:
    factory = _session_factory()
    run_id, child_id = _run_waiting_for_content_wave(
        factory,
        status=OperationStatus.PARTIAL,
        result_summary={
            "fetch_succeeded": 3,
            "event_manifest_complete": True,
            "event_manifest_count": 0,
        },
    )

    DailyAutopilotHandler(factory)(
        _lease(run_id, DailyAutopilotStage.WAIT_CONTENT_WAVE), lambda _boundary: None
    )

    with factory() as db:
        saved = DailyAutopilotRepository(db).get(run_id)
        assert saved.status == "succeeded"
        assert saved.stage == DailyAutopilotStage.COMPLETED.value
        assert saved.result_summary["outcome"] == "no_content"
        assert saved.result_summary["event_operation_id"] == child_id
        assert saved.daily_report_id is None


def test_content_wave_without_successful_fetch_fails_collection() -> None:
    factory = _session_factory()
    run_id, _child_id = _run_waiting_for_content_wave(
        factory,
        status=OperationStatus.PARTIAL,
        result_summary={
            "fetch_succeeded": 0,
            "event_manifest_complete": True,
            "event_manifest_count": 0,
        },
    )

    DailyAutopilotHandler(factory)(
        _lease(run_id, DailyAutopilotStage.WAIT_CONTENT_WAVE), lambda _boundary: None
    )

    with factory() as db:
        saved = DailyAutopilotRepository(db).get(run_id)
        assert saved.status == "failed"
        assert saved.error_code == "daily_autopilot_content_not_fetched"
        assert "没有来源完成真实抓取" in saved.error_message


def test_content_wave_with_incomplete_manifest_fails_with_chinese_diagnostic() -> None:
    factory = _session_factory()
    run_id, _child_id = _run_waiting_for_content_wave(
        factory,
        status=OperationStatus.PARTIAL,
        result_summary={
            "fetch_succeeded": 2,
            "event_manifest_complete": False,
            "event_manifest_count": 0,
        },
    )

    DailyAutopilotHandler(factory)(
        _lease(run_id, DailyAutopilotStage.WAIT_CONTENT_WAVE), lambda _boundary: None
    )

    with factory() as db:
        saved = DailyAutopilotRepository(db).get(run_id)
        assert saved.status == "failed"
        assert saved.error_code == "daily_autopilot_event_manifest_incomplete"
        assert "事件清单" in saved.error_message


def test_failed_content_wave_preserves_child_chinese_diagnostic() -> None:
    factory = _session_factory()
    run_id, _child_id = _run_waiting_for_content_wave(
        factory,
        status=OperationStatus.FAILED,
        result_summary={},
        error_code="network_unavailable",
        error_message="所有目标均未完成真实抓取，请检查网络诊断。",
    )

    DailyAutopilotHandler(factory)(
        _lease(run_id, DailyAutopilotStage.WAIT_CONTENT_WAVE), lambda _boundary: None
    )

    with factory() as db:
        saved = DailyAutopilotRepository(db).get(run_id)
        assert saved.status == "failed"
        assert saved.error_code == "network_unavailable"
        assert saved.error_message == "所有目标均未完成真实抓取，请检查网络诊断。"
