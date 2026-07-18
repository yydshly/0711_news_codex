"""Single-worker-safe orchestration for the automatic daily report."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from newsradar.daily_reports.autopilot import (
    TERMINAL_AUTOPILOT_STAGES,
    DailyAutopilotStage,
    build_decision_review,
    build_overview_review,
    deserialize_catalog_plan,
    deserialize_wave_plan,
)
from newsradar.daily_reports.autopilot_repository import DailyAutopilotRepository
from newsradar.daily_reports.chinese_enrichment import (
    DailyReportChineseCandidate,
    DailyReportChineseEnricher,
    DailyReportChineseResult,
    rule_based_chinese_copy,
)
from newsradar.daily_reports.repository import DailyReportRepository
from newsradar.daily_reports.service import DailyReportService
from newsradar.db.models import DailyAutopilotRunRecord, DailyReportRecord, OperationRunRecord
from newsradar.operations.commands import OperationCommandService
from newsradar.operations.repository import OperationLease, OperationRepository
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.operations.worker import OperationCancelled, OperationResult
from newsradar.settings import Settings, get_settings

_WAIT_SECONDS = 15
_RUNNING_STATUSES = {OperationStatus.QUEUED.value, OperationStatus.RUNNING.value}


class DailyAutopilotHandler:
    """Advance exactly one short stage, then queue the next continuation.

    This deliberately never waits for a child operation.  A single Worker can
    therefore lease source refresh, event processing and audio tasks between
    these continuations instead of deadlocking behind its own parent task.
    """

    def __init__(
        self,
        create_session: Callable[[], AbstractContextManager[Session]],
        *,
        utcnow: Callable[[], datetime] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._create_session = create_session
        self._utcnow = utcnow or (lambda: datetime.now(UTC))
        self._settings = settings or get_settings()

    @classmethod
    def production(
        cls,
        sources: object,
        providers: object,
        create_session: Callable[[], AbstractContextManager[Session]],
    ) -> DailyAutopilotHandler:
        # The source plan was frozen before the operation was queued.  Keeping
        # these parameters makes Worker registration explicit while ensuring a
        # later catalog edit cannot change an in-flight run.
        del sources, providers
        return cls(create_session)

    def __call__(
        self, lease: OperationLease, checkpoint: Callable[[str], None]
    ) -> OperationResult:
        if lease.operation_type != OperationType.DAILY_AUTOPILOT.value:
            return _failed("unsupported_operation_type", "不支持的自动日报任务类型。")
        run_id = lease.requested_scope.get("daily_autopilot_run_id")
        stage_value = lease.requested_scope.get("stage")
        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
            return _failed("invalid_daily_autopilot_scope", "自动日报任务参数无效。")
        try:
            stage = DailyAutopilotStage(stage_value)
        except (TypeError, ValueError):
            return _failed("invalid_daily_autopilot_scope", "自动日报阶段参数无效。")
        checkpoint(f"daily_autopilot:{stage.value}")

        try:
            run = self._run(run_id)
        except LookupError:
            return _failed("daily_autopilot_not_found", "自动日报任务不存在。")
        if DailyAutopilotStage(run.stage) in TERMINAL_AUTOPILOT_STAGES:
            return _succeeded({"run_id": run_id, "idempotent": True, "terminal": run.stage})
        if run.stage != stage.value:
            return _succeeded({"run_id": run_id, "idempotent": True, "current_stage": run.stage})

        try:
            return self._advance(run, stage, checkpoint)
        except OperationCancelled:
            raise
        except ValueError as exc:
            self._fail(run_id, "daily_autopilot_validation", _diagnostic_message(str(exc)))
            return _succeeded({"run_id": run_id, "failed": True})
        except Exception:
            self._fail(
                run_id,
                "daily_autopilot_internal",
                "自动日报处理出现内部错误，已停止后续步骤，请查看关联任务的中文诊断。",
            )
            return _succeeded({"run_id": run_id, "failed": True})

    def _advance(
        self,
        run: DailyAutopilotRunRecord,
        stage: DailyAutopilotStage,
        checkpoint: Callable[[str], None],
    ) -> OperationResult:
        if stage is DailyAutopilotStage.ENQUEUE_CONTENT_WAVE:
            return self._enqueue_content_wave(run, checkpoint)
        if stage is DailyAutopilotStage.WAIT_CONTENT_WAVE:
            return self._wait_for_content_wave(run)
        if stage is DailyAutopilotStage.ENQUEUE_SOURCE_REFRESH:
            return self._enqueue_source_refresh(run, checkpoint)
        if stage is DailyAutopilotStage.WAIT_SOURCE_REFRESH:
            return self._wait_for_child(
                run,
                child_id=run.source_operation_id,
                waiting_stage=stage,
                next_stage=DailyAutopilotStage.ENQUEUE_EVENT_PIPELINE,
                allowed_terminal={OperationStatus.SUCCEEDED.value, OperationStatus.PARTIAL.value},
                child_label="来源刷新",
            )
        if stage is DailyAutopilotStage.ENQUEUE_EVENT_PIPELINE:
            return self._enqueue_event_pipeline(run, checkpoint)
        if stage is DailyAutopilotStage.WAIT_EVENT_PIPELINE:
            return self._wait_for_child(
                run,
                child_id=run.event_operation_id,
                waiting_stage=stage,
                next_stage=DailyAutopilotStage.GENERATE_REPORT,
                allowed_terminal={OperationStatus.SUCCEEDED.value},
                child_label="事件处理",
            )
        if stage is DailyAutopilotStage.GENERATE_REPORT:
            return self._generate_report(run, checkpoint)
        if stage is DailyAutopilotStage.WRITE_REVIEWS:
            return self._write_reviews(run, checkpoint)
        if stage is DailyAutopilotStage.ARCHIVE_AND_ENQUEUE_AUDIO:
            return self._archive_and_enqueue_audio(run, checkpoint)
        if stage is DailyAutopilotStage.WAIT_AUDIO:
            return self._wait_for_audio(run)
        return _failed("invalid_daily_autopilot_stage", "自动日报处于不可执行阶段。")

    def _enqueue_content_wave(
        self, run: DailyAutopilotRunRecord, checkpoint: Callable[[str], None]
    ) -> OperationResult:
        if run.event_operation_id is not None:
            self._transition_and_continue(
                run.id, DailyAutopilotStage.WAIT_CONTENT_WAVE, delayed=True
            )
            return _succeeded({"run_id": run.id, "idempotent": True})
        plan = deserialize_wave_plan(run.requested_scope.get("wave_plan"))
        checkpoint("daily_autopilot:enqueue_high_value_wave")
        try:
            with self._create_session() as session:
                operation_id = OperationCommandService(
                    session, utcnow=self._utcnow
                ).enqueue_high_value_wave(plan=plan, trigger="autopilot")
        except ValueError as exc:
            if str(exc) == "active_high_value_wave_exists":
                self._transition_and_continue(
                    run.id,
                    DailyAutopilotStage.ENQUEUE_CONTENT_WAVE,
                    delayed=True,
                )
                return _succeeded({"run_id": run.id, "waiting_for_content_wave": True})
            raise
        self._transition_and_continue(
            run.id,
            DailyAutopilotStage.WAIT_CONTENT_WAVE,
            event_operation_id=operation_id,
            delayed=True,
        )
        return _succeeded({"run_id": run.id, "event_operation_id": operation_id})

    def _wait_for_content_wave(self, run: DailyAutopilotRunRecord) -> OperationResult:
        child_id = run.event_operation_id
        if child_id is None:
            self._fail(
                run.id,
                "daily_autopilot_child_missing",
                "内容抓取与事件处理任务未创建。",
            )
            return _succeeded({"run_id": run.id, "failed": True})
        child = self._operation(child_id)
        if child is None or child.operation_type != OperationType.HIGH_VALUE_NEWS_WAVE.value:
            self._fail(
                run.id,
                "daily_autopilot_child_missing",
                "内容抓取与事件处理任务不存在或类型不正确。",
            )
            return _succeeded({"run_id": run.id, "failed": True})
        if child.status in _RUNNING_STATUSES:
            self._transition_and_continue(
                run.id, DailyAutopilotStage.WAIT_CONTENT_WAVE, delayed=True
            )
            return _succeeded({"run_id": run.id, "waiting_for_operation_id": child.id})
        if child.status not in {
            OperationStatus.SUCCEEDED.value,
            OperationStatus.PARTIAL.value,
        }:
            self._fail(
                run.id,
                child.error_code or "daily_autopilot_content_wave_failed",
                child.error_message or "内容抓取与事件处理任务未能完成。",
            )
            return _succeeded(
                {"run_id": run.id, "failed": True, "child_status": child.status}
            )
        summary = child.result_summary if isinstance(child.result_summary, dict) else {}
        fetch_succeeded = _summary_count(summary, "fetch_succeeded")
        event_count = _summary_count(summary, "event_manifest_count")
        if summary.get("event_manifest_complete") is not True or event_count is None:
            self._fail(
                run.id,
                "daily_autopilot_event_manifest_incomplete",
                "真实抓取任务未形成完整事件清单，不能据此生成日报。",
            )
            return _succeeded({"run_id": run.id, "failed": True})
        if fetch_succeeded is None or fetch_succeeded == 0:
            self._fail(
                run.id,
                "daily_autopilot_content_not_fetched",
                "本次波次没有来源完成真实抓取，不能把目录探测结果当作今日新闻。",
            )
            return _succeeded({"run_id": run.id, "failed": True})
        if event_count == 0:
            self._finish(
                run.id,
                {
                    "outcome": "no_content",
                    "event_operation_id": child.id,
                    "fetch_succeeded": fetch_succeeded,
                    "event_manifest_count": 0,
                },
            )
            return _succeeded({"run_id": run.id, "completed": True, "no_content": True})
        self._transition_and_continue(run.id, DailyAutopilotStage.GENERATE_REPORT)
        return _succeeded(
            {
                "run_id": run.id,
                "child_status": child.status,
                "event_manifest_count": event_count,
            }
        )

    def _enqueue_source_refresh(
        self, run: DailyAutopilotRunRecord, checkpoint: Callable[[str], None]
    ) -> OperationResult:
        if run.source_operation_id is not None:
            self._transition_and_continue(run.id, DailyAutopilotStage.WAIT_SOURCE_REFRESH)
            return _succeeded({"run_id": run.id, "idempotent": True})
        plan = deserialize_catalog_plan(run.requested_scope.get("catalog_plan"))
        checkpoint("daily_autopilot:enqueue_source_catalog_refresh")
        try:
            with self._create_session() as session:
                commands = OperationCommandService(session, utcnow=self._utcnow)
                operation_id = commands.enqueue_source_catalog_refresh(
                    plan,
                    trigger="autopilot",
                )
        except ValueError as exc:
            if str(exc) == "active_catalog_refresh_exists":
                self._transition_and_continue(
                    run.id,
                    DailyAutopilotStage.ENQUEUE_SOURCE_REFRESH,
                    delayed=True,
                )
                return _succeeded({"run_id": run.id, "waiting_for_catalog_refresh": True})
            raise
        self._transition_and_continue(
            run.id,
            DailyAutopilotStage.WAIT_SOURCE_REFRESH,
            source_operation_id=operation_id,
            delayed=True,
        )
        return _succeeded({"run_id": run.id, "source_operation_id": operation_id})

    def _enqueue_event_pipeline(
        self, run: DailyAutopilotRunRecord, checkpoint: Callable[[str], None]
    ) -> OperationResult:
        if run.event_operation_id is not None:
            self._transition_and_continue(run.id, DailyAutopilotStage.WAIT_EVENT_PIPELINE)
            return _succeeded({"run_id": run.id, "idempotent": True})
        checkpoint("daily_autopilot:enqueue_event_pipeline")
        with self._create_session() as session:
            commands = OperationCommandService(session, utcnow=self._utcnow)
            operation_id = commands.enqueue_event_pipeline(
                window_hours=run.window_hours,
                trigger="autopilot",
            )
        self._transition_and_continue(
            run.id,
            DailyAutopilotStage.WAIT_EVENT_PIPELINE,
            event_operation_id=operation_id,
            delayed=True,
        )
        return _succeeded({"run_id": run.id, "event_operation_id": operation_id})

    def _wait_for_child(
        self,
        run: DailyAutopilotRunRecord,
        *,
        child_id: int | None,
        waiting_stage: DailyAutopilotStage,
        next_stage: DailyAutopilotStage,
        allowed_terminal: set[str],
        child_label: str,
    ) -> OperationResult:
        if child_id is None:
            self._fail(run.id, "daily_autopilot_child_missing", f"{child_label}任务未创建。")
            return _succeeded({"run_id": run.id, "failed": True})
        child = self._operation(child_id)
        if child is None:
            self._fail(run.id, "daily_autopilot_child_missing", f"{child_label}任务不存在。")
            return _succeeded({"run_id": run.id, "failed": True})
        if child.status in _RUNNING_STATUSES:
            self._transition_and_continue(run.id, waiting_stage, delayed=True)
            return _succeeded({"run_id": run.id, "waiting_for_operation_id": child.id})
        if child.status in allowed_terminal:
            self._transition_and_continue(run.id, next_stage)
            return _succeeded({"run_id": run.id, "child_status": child.status})
        self._fail(
            run.id,
            child.error_code or "daily_autopilot_child_failed",
            child.error_message or f"{child_label}任务未能完成。",
        )
        return _succeeded({"run_id": run.id, "failed": True, "child_status": child.status})

    def _generate_report(
        self, run: DailyAutopilotRunRecord, checkpoint: Callable[[str], None]
    ) -> OperationResult:
        if run.daily_report_id is None:
            if run.event_operation_id is None:
                raise ValueError("daily_autopilot_event_operation_missing")
            checkpoint("daily_autopilot:generate_report")
            with self._create_session() as session:
                report_id = DailyReportService(
                    session, utcnow=self._utcnow
                ).generate_from_operation(
                    run.event_operation_id,
                    run.window_hours,
                ).id
        else:
            report_id = run.daily_report_id
        self._transition_and_continue(
            run.id,
            DailyAutopilotStage.WRITE_REVIEWS,
            daily_report_id=report_id,
        )
        return _succeeded({"run_id": run.id, "daily_report_id": report_id})

    def _write_reviews(
        self, run: DailyAutopilotRunRecord, checkpoint: Callable[[str], None]
    ) -> OperationResult:
        if run.daily_report_id is None:
            raise ValueError("daily_report_not_found")
        with self._create_session() as session:
            reports = DailyReportRepository(session, utcnow=self._utcnow)
            candidates = reports.chinese_enrichment_candidates(run.daily_report_id)
            completed = reports.completed_chinese_enrichment_keys(run.daily_report_id)

        pending = tuple(row for row in candidates if row.key not in completed)
        budget = self._settings.daily_report_model_max_items
        model_keys = {row.key for row in candidates[:budget]}
        for offset in range(0, len(pending), 2):
            batch = pending[offset : offset + 2]
            callable_rows = tuple(row for row in batch if row.key in model_keys)
            results = list(self._run_chinese_enrichment(callable_rows, checkpoint))
            results.extend(
                _budget_result_for(row, self._settings.minimax_fast_model)
                for row in batch
                if row.key not in model_keys
            )
            for result in results:
                checkpoint("daily_autopilot:save_chinese_enrichment_item")
                decision = (
                    build_decision_review(
                        result.candidate.snapshot,
                        zh_title=result.copy.zh_title,
                        zh_summary=result.copy.zh_summary,
                        review_recommendation=result.copy.review_recommendation,
                        evidence_assessment=result.copy.evidence_assessment,
                    )
                    if result.candidate.decision_item_id is not None
                    else None
                )
                overview = (
                    build_overview_review(
                        result.candidate.snapshot,
                        zh_title=result.copy.zh_title,
                        zh_summary=result.copy.zh_summary,
                        review_recommendation=result.copy.review_recommendation,
                        evidence_assessment=result.copy.evidence_assessment,
                    )
                    if result.candidate.overview_item_id is not None
                    else None
                )
                with self._create_session() as session:
                    DailyReportRepository(
                        session, utcnow=self._utcnow
                    ).save_automatic_chinese_reviews(
                        run.daily_report_id,
                        result,
                        decision,
                        overview,
                        candidate_total=len(candidates),
                        model_budget=budget,
                    )

        with self._create_session() as session:
            report = session.get(DailyReportRecord, run.daily_report_id)
            if report is None:
                raise ValueError("daily_report_not_found")
            summary = dict(report.generation_summary.get("daily_chinese_enrichment") or {})
        self._transition_and_continue(run.id, DailyAutopilotStage.ARCHIVE_AND_ENQUEUE_AUDIO)
        return _succeeded({"run_id": run.id, **summary})

    def _run_chinese_enrichment(
        self,
        candidates: tuple[DailyReportChineseCandidate, ...],
        checkpoint: Callable[[str], None],
    ) -> tuple[DailyReportChineseResult, ...]:
        if not candidates:
            return ()

        async def run() -> tuple[DailyReportChineseResult, ...]:
            import httpx

            async with httpx.AsyncClient() as http:
                return await DailyReportChineseEnricher(
                    self._settings, http
                ).enrich_batch(candidates, checkpoint)

        return asyncio.run(run())

    def _archive_and_enqueue_audio(
        self, run: DailyAutopilotRunRecord, checkpoint: Callable[[str], None]
    ) -> OperationResult:
        if run.daily_report_id is None:
            raise ValueError("daily_report_not_found")
        checkpoint("daily_autopilot:archive_report")
        decision_id = run.decision_audio_operation_id
        overview_id = run.overview_audio_operation_id
        if decision_id is None or overview_id is None:
            with self._create_session() as session:
                decision_id, overview_id = OperationCommandService(
                    session, utcnow=self._utcnow
                ).archive_and_enqueue_daily_report_audios(
                    report_id=run.daily_report_id,
                    trigger="autopilot",
                )
        self._transition_and_continue(
            run.id,
            DailyAutopilotStage.WAIT_AUDIO,
            decision_audio_operation_id=decision_id,
            overview_audio_operation_id=overview_id,
            delayed=True,
        )
        return _succeeded(
            {
                "run_id": run.id,
                "decision_audio_operation_id": decision_id,
                "overview_audio_operation_id": overview_id,
            }
        )

    def _wait_for_audio(self, run: DailyAutopilotRunRecord) -> OperationResult:
        child_ids = (run.decision_audio_operation_id, run.overview_audio_operation_id)
        if any(child_id is None for child_id in child_ids):
            self._fail(run.id, "daily_autopilot_audio_missing", "日报音频任务未创建。")
            return _succeeded({"run_id": run.id, "failed": True})
        children = [self._operation(child_id) for child_id in child_ids]
        if any(child is None for child in children):
            self._fail(run.id, "daily_autopilot_audio_missing", "日报音频任务不存在。")
            return _succeeded({"run_id": run.id, "failed": True})
        operations = [child for child in children if child is not None]
        successful_or_running = _RUNNING_STATUSES | {OperationStatus.SUCCEEDED.value}
        failed_child = next(
            (child for child in operations if child.status not in successful_or_running), None
        )
        if failed_child is not None:
            self._fail(
                run.id,
                failed_child.error_code or "daily_autopilot_audio_failed",
                failed_child.error_message or "日报音频生成失败。",
            )
            return _succeeded({"run_id": run.id, "failed": True})
        if any(child.status in _RUNNING_STATUSES for child in operations):
            self._transition_and_continue(run.id, DailyAutopilotStage.WAIT_AUDIO, delayed=True)
            return _succeeded({"run_id": run.id, "waiting_for_audio": True})
        self._finish(run.id, {"daily_report_id": run.daily_report_id, "audio_count": 2})
        return _succeeded({"run_id": run.id, "completed": True})

    def _run(self, run_id: int) -> DailyAutopilotRunRecord:
        with self._create_session() as session:
            return DailyAutopilotRepository(session).get(run_id)

    def _operation(self, operation_id: int) -> OperationRunRecord | None:
        with self._create_session() as session:
            return session.get(OperationRunRecord, operation_id)

    def _transition_and_continue(
        self,
        run_id: int,
        stage: DailyAutopilotStage,
        *,
        delayed: bool = False,
        **ids: int,
    ) -> None:
        with self._create_session() as session, session.begin():
            runs = DailyAutopilotRepository(session, utcnow=self._utcnow)
            runs.transition(run_id, stage=stage, **ids)
            OperationRepository(session).enqueue(
                OperationType.DAILY_AUTOPILOT,
                {"daily_autopilot_run_id": run_id, "stage": stage.value},
                trigger="autopilot",
                in_transaction=True,
                not_before=(self._utcnow() + timedelta(seconds=_WAIT_SECONDS)) if delayed else None,
            )

    def _fail(self, run_id: int, code: str, message: str) -> None:
        with self._create_session() as session, session.begin():
            DailyAutopilotRepository(session, utcnow=self._utcnow).fail(run_id, code, message)

    def _finish(self, run_id: int, result_summary: dict[str, Any]) -> None:
        with self._create_session() as session, session.begin():
            run = DailyAutopilotRepository(session, utcnow=self._utcnow).transition(
                run_id,
                stage=DailyAutopilotStage.COMPLETED,
                status="succeeded",
            )
            run.result_summary = result_summary


def _succeeded(summary: dict[str, Any]) -> OperationResult:
    return OperationResult(
        status=OperationStatus.SUCCEEDED,
        result_summary=summary,
        retryable=False,
    )


def _failed(code: str, message: str) -> OperationResult:
    return OperationResult(
        status=OperationStatus.FAILED,
        error_code=code,
        error_message=message,
        retryable=False,
    )


def _summary_count(summary: dict[str, Any], key: str) -> int | None:
    value = summary.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _budget_result_for(
    candidate: DailyReportChineseCandidate, model: str
) -> DailyReportChineseResult:
    return DailyReportChineseResult(
        candidate=candidate,
        copy=rule_based_chinese_copy(candidate.snapshot),
        origin="budget_limit",
        error_code="budget_limit",
        model=model,
        usages=(),
    )


def _diagnostic_message(code: str) -> str:
    messages = {
        "complete_event_snapshot_required": "事件处理尚未形成可用于日报的完整快照。",
        "daily_autopilot_event_operation_missing": "自动日报缺少本次真实抓取任务，不能生成报告。",
        "daily_report_not_found": "自动日报关联的报告不存在。",
        "daily_report_decision_has_no_items": "决策简报没有可审核条目，不能生成语音。",
        "daily_report_decision_review_incomplete": "决策简报尚未完成全部中文审核。",
        "daily_report_decision_has_no_included_items": "决策简报审核后没有可播报条目。",
        "daily_report_overview_has_no_items": "情报全览没有可审核条目，不能生成语音。",
        "daily_report_overview_review_incomplete": "情报全览尚未完成审核，不能生成音频。",
        "daily_report_overview_has_no_included_items": "情报全览没有可播报条目。",
        "daily_report_audio_package_incomplete": (
            "日报双版本语音任务不完整，请使用单版本恢复入口处理。"
        ),
        "daily_report_must_be_archived_for_audio": "日报尚未归档，不能生成音频。",
    }
    return messages.get(code, "自动日报处理失败，请查看关联任务的中文诊断。")
