from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from newsradar.ai.minimax import ModelUsage
from newsradar.daily_reports import autopilot_runtime
from newsradar.daily_reports.autopilot import (
    DailyAutopilotStage,
    build_decision_review,
    build_overview_review,
    serialize_catalog_plan,
    serialize_wave_plan,
)
from newsradar.daily_reports.autopilot_repository import DailyAutopilotRepository
from newsradar.daily_reports.autopilot_runtime import DailyAutopilotHandler
from newsradar.daily_reports.chinese_enrichment import (
    DailyReportChineseCopy,
    DailyReportChineseEnricher,
    DailyReportChineseResult,
)
from newsradar.daily_reports.repository import DailyReportRepository
from newsradar.daily_reports.schema import (
    DailyReportDraft,
    DailyReportItemDraft,
    DailyReportOverviewItemDraft,
    ReportSection,
)
from newsradar.db.models import Base, DailyReportRecord, EventRecord, OperationRunRecord
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.settings import Settings
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


def _seed_autopilot_report(factory, *, event_count: int = 2, completed_count: int = 0):
    with factory() as db:
        operation = OperationRunRecord(
            operation_type=OperationType.HIGH_VALUE_NEWS_WAVE.value,
            trigger="test",
            status=OperationStatus.SUCCEEDED.value,
            requested_scope={},
            result_summary={"event_manifest_complete": True},
        )
        db.add(operation)
        db.flush()
        items = []
        overview_items = []
        for position in range(1, event_count + 1):
            event_id = 100 + position
            db.add(
                EventRecord(
                    id=event_id,
                    canonical_key=f"autopilot-chinese-{event_id}",
                    status="emerging",
                    current_version_number=1,
                    occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
                )
            )
            snapshot = {
                "status": "emerging",
                "independent_root_count": 0,
                "zh_title": f"English {event_id}",
                "zh_summary": f"English summary {event_id}",
            }
            items.append(
                DailyReportItemDraft(
                    event_id=event_id,
                    event_version_number=1,
                    section=ReportSection.EMERGING,
                    position=position,
                    snapshot=snapshot,
                )
            )
            overview_items.append(
                DailyReportOverviewItemDraft(
                    event_id=event_id,
                    event_version_number=1,
                    position=position,
                    snapshot=snapshot,
                    decision_event_id=event_id,
                )
            )
        db.flush()
        report = DailyReportRepository(db).create_draft(
            DailyReportDraft(
                report_date=date(2026, 7, 18),
                window_hours=24,
                window_start=datetime(2026, 7, 17, tzinfo=UTC),
                window_end=datetime(2026, 7, 18, tzinfo=UTC),
                source_operation_id=operation.id,
                generation_summary={"confirmed_count": 0, "emerging_count": event_count},
                items=tuple(items),
                overview_items=tuple(overview_items),
            )
        )
        run = DailyAutopilotRepository(db).create_run(
            window_hours=24,
            trigger="test",
            requested_scope={"wave_plan": serialize_wave_plan(_wave_plan())},
        )
        DailyAutopilotRepository(db).transition(
            run.id,
            stage=DailyAutopilotStage.WRITE_REVIEWS,
            daily_report_id=report.id,
            event_operation_id=operation.id,
        )
        report_id = report.id
        run_id = run.id
        db.commit()
        run_view = SimpleNamespace(id=run_id, daily_report_id=report_id)

    if completed_count:
        with factory() as db:
            repository = DailyReportRepository(db)
            for row in repository.chinese_enrichment_candidates(report_id)[:completed_count]:
                result = _model_result_for(row)
                repository.save_automatic_chinese_reviews(
                    report_id,
                    result,
                    build_decision_review(
                        row.snapshot,
                        zh_title=result.copy.zh_title,
                        zh_summary=result.copy.zh_summary,
                    ),
                    build_overview_review(
                        row.snapshot,
                        zh_title=result.copy.zh_title,
                        zh_summary=result.copy.zh_summary,
                    ),
                    candidate_total=event_count,
                    model_budget=60,
                )
    return run_view


def _load_enrichment_summary(factory, report_id: int) -> dict[str, object]:
    with factory() as db:
        report = db.get(DailyReportRecord, report_id)
        assert report is not None
        return dict(report.generation_summary["daily_chinese_enrichment"])


def _model_result_for(candidate) -> DailyReportChineseResult:
    return DailyReportChineseResult(
        candidate=candidate,
        copy=DailyReportChineseCopy("模型中文标题", "模型生成的中文文章概述。"),
        origin="model",
        error_code=None,
        model="MiniMax-M2.7-highspeed",
        usages=(
            ModelUsage(
                purpose="daily_report_chinese_enrichment",
                model="MiniMax-M2.7-highspeed",
                input_tokens=20,
                output_tokens=10,
                latency_ms=12.5,
                outcome="success",
            ),
        ),
    )


def _fallback_result_for(candidate, error_code: str) -> DailyReportChineseResult:
    result = _model_result_for(candidate)
    return replace(
        result,
        copy=DailyReportChineseCopy(
            zh_title=str(candidate.snapshot["zh_title"]),
            zh_summary=str(candidate.snapshot["zh_summary"]),
        ),
        origin="rule_fallback",
        error_code=error_code,
        usages=(replace(result.usages[0], outcome="fallback", error=error_code),),
    )


def test_write_reviews_enriches_each_unique_event_once_and_reuses_copy(monkeypatch) -> None:
    factory = _session_factory()
    run = _seed_autopilot_report(factory)
    calls: list[str] = []

    async def enrich_batch(self, candidates, checkpoint=None):
        calls.extend(row.key for row in candidates)
        return tuple(_model_result_for(row) for row in candidates)

    monkeypatch.setattr(DailyReportChineseEnricher, "enrich_batch", enrich_batch)
    result = DailyAutopilotHandler(factory)._write_reviews(run, lambda _phase: None)

    assert result.status is OperationStatus.SUCCEEDED
    assert calls == ["101:1", "102:1"]
    assert result.result_summary["model_success"] == 2


def test_write_reviews_continues_after_one_model_fallback(monkeypatch) -> None:
    factory = _session_factory()
    run = _seed_autopilot_report(factory)

    async def enrich_batch(self, candidates, checkpoint=None):
        return tuple(
            _fallback_result_for(row, "http_429")
            if row.event_id == 101
            else _model_result_for(row)
            for row in candidates
        )

    monkeypatch.setattr(DailyReportChineseEnricher, "enrich_batch", enrich_batch)
    result = DailyAutopilotHandler(factory)._write_reviews(run, lambda _phase: None)

    assert result.status is OperationStatus.SUCCEEDED
    assert result.result_summary["model_success"] == 1
    assert result.result_summary["rule_fallback"] == 1
    assert result.result_summary["error_counts"] == {"http_429": 1}


def test_write_reviews_resume_skips_completed_event(monkeypatch) -> None:
    factory = _session_factory()
    run = _seed_autopilot_report(factory, completed_count=1)
    calls: list[str] = []

    async def enrich_batch(self, candidates, checkpoint=None):
        calls.extend(row.key for row in candidates)
        return tuple(_model_result_for(row) for row in candidates)

    monkeypatch.setattr(DailyReportChineseEnricher, "enrich_batch", enrich_batch)
    DailyAutopilotHandler(factory)._write_reviews(run, lambda _phase: None)

    assert calls == ["102:1"]


def test_write_reviews_marks_items_beyond_local_limit_without_calling_model(monkeypatch) -> None:
    factory = _session_factory()
    run = _seed_autopilot_report(factory, event_count=3)
    settings = Settings(_env_file=None, daily_report_model_max_items=2, minimax_api_key="secret")
    calls: list[str] = []

    async def enrich_batch(self, candidates, checkpoint=None):
        calls.extend(row.key for row in candidates)
        return tuple(_model_result_for(row) for row in candidates)

    monkeypatch.setattr(DailyReportChineseEnricher, "enrich_batch", enrich_batch)
    handler = DailyAutopilotHandler(factory, settings=settings)
    handler._write_reviews(run, lambda _phase: None)

    assert calls == ["101:1", "102:1"]
    assert _load_enrichment_summary(factory, run.daily_report_id)["budget_fallback"] == 1


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


def test_generate_report_uses_exact_child_and_reads_id_before_session_closes(monkeypatch) -> None:
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

        def generate_from_operation(
            self, operation_id: int, window_hours: int
        ) -> GeneratedReport:
            assert operation_id == 88
            assert window_hours == 24
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
        SimpleNamespace(
            id=9,
            daily_report_id=None,
            event_operation_id=88,
            window_hours=24,
        ),
        lambda _boundary: None,
    )

    assert result.status is OperationStatus.SUCCEEDED
    assert transitions == [(9, DailyAutopilotStage.WRITE_REVIEWS, {"daily_report_id": 41})]


def test_generate_report_rejects_missing_content_operation() -> None:
    handler = DailyAutopilotHandler(lambda: None)

    with pytest.raises(ValueError, match="daily_autopilot_event_operation_missing"):
        handler._generate_report(
            SimpleNamespace(
                id=9,
                daily_report_id=None,
                event_operation_id=None,
                window_hours=24,
            ),
            lambda _boundary: None,
        )


def test_archive_stage_enqueues_both_audio_renditions_as_one_package(monkeypatch) -> None:
    class SessionContext:
        def __enter__(self):
            return object()

        def __exit__(self, *_args) -> None:
            return None

    calls: list[tuple[int, str]] = []

    class Commands:
        def __init__(self, _session, **_kwargs) -> None:
            pass

        def archive_and_enqueue_daily_report_audios(
            self, *, report_id: int, trigger: str
        ) -> tuple[int, int]:
            calls.append((report_id, trigger))
            return 51, 52

    handler = DailyAutopilotHandler(lambda: SessionContext())
    transitions: list[tuple[int, DailyAutopilotStage, dict[str, int | bool]]] = []
    monkeypatch.setattr(autopilot_runtime, "OperationCommandService", Commands)
    monkeypatch.setattr(
        handler,
        "_transition_and_continue",
        lambda run_id, stage, **ids: transitions.append((run_id, stage, ids)),
    )

    result = handler._archive_and_enqueue_audio(
        SimpleNamespace(
            id=9,
            daily_report_id=41,
            decision_audio_operation_id=None,
            overview_audio_operation_id=None,
        ),
        lambda _boundary: None,
    )

    assert result.status is OperationStatus.SUCCEEDED
    assert calls == [(41, "autopilot")]
    assert transitions == [
        (
            9,
            DailyAutopilotStage.WAIT_AUDIO,
            {
                "decision_audio_operation_id": 51,
                "overview_audio_operation_id": 52,
                "delayed": True,
            },
        )
    ]


def test_archive_stage_is_idempotent_for_existing_audio_pair(monkeypatch) -> None:
    handler = DailyAutopilotHandler(lambda: pytest.fail("must not open a session"))
    transitions: list[tuple[int, DailyAutopilotStage, dict[str, int | bool]]] = []
    monkeypatch.setattr(
        handler,
        "_transition_and_continue",
        lambda run_id, stage, **ids: transitions.append((run_id, stage, ids)),
    )

    handler._archive_and_enqueue_audio(
        SimpleNamespace(
            id=9,
            daily_report_id=41,
            decision_audio_operation_id=51,
            overview_audio_operation_id=52,
        ),
        lambda _boundary: None,
    )

    assert transitions[0][2]["decision_audio_operation_id"] == 51
    assert transitions[0][2]["overview_audio_operation_id"] == 52


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
