"""Read-only views for resumable automatic daily-report runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    DailyAutopilotRunRecord,
    DailyReportRecord,
    FetchRunRecord,
    OperationRunRecord,
)
from newsradar.web.daily_report_queries import (
    DailyReportChineseEnrichmentView,
    _chinese_enrichment_view,
)


@dataclass(frozen=True, slots=True)
class DailyAutopilotOperationView:
    operation_id: int
    status: str
    progress_current: int
    progress_total: int | None
    error_code: str | None
    error_message: str | None
    metrics: dict[str, int]


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
class DailyAutopilotCoverageView:
    planned_targets: int | None
    fetch_succeeded: int | None
    blocked_targets: int | None
    formed_events: int | None
    decision_items: int | None
    overview_items: int | None
    omitted_from_overview: int | None


@dataclass(frozen=True, slots=True)
class DailyAutopilotDetailView(DailyAutopilotSummaryView):
    error_code: str | None
    error_message: str | None
    result_summary: dict[str, object]
    source_operation: DailyAutopilotOperationView | None
    event_operation: DailyAutopilotOperationView | None
    decision_audio_operation: DailyAutopilotOperationView | None
    overview_audio_operation: DailyAutopilotOperationView | None
    chinese_enrichment: DailyReportChineseEnrichmentView
    coverage: DailyAutopilotCoverageView
    audio_partial_message_zh: str | None
    next_action_zh: str


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
        source_operation = self._operation(row.source_operation_id)
        event_operation = self._operation(row.event_operation_id)
        decision_audio = self._operation(row.decision_audio_operation_id)
        overview_audio = self._operation(row.overview_audio_operation_id)
        chinese_enrichment = self._chinese_enrichment(row.daily_report_id)
        coverage = self._coverage(row, event_operation)
        summary = dict(row.result_summary) if isinstance(row.result_summary, dict) else {}
        return DailyAutopilotDetailView(
            **asdict(self._summary(row)),
            error_code=row.error_code,
            error_message=row.error_message,
            result_summary=summary,
            source_operation=source_operation,
            event_operation=event_operation,
            decision_audio_operation=decision_audio,
            overview_audio_operation=overview_audio,
            chinese_enrichment=chinese_enrichment,
            coverage=coverage,
            audio_partial_message_zh=_audio_partial_message(summary),
            next_action_zh=_next_action(row, event_operation),
        )

    def _chinese_enrichment(
        self, report_id: int | None
    ) -> DailyReportChineseEnrichmentView:
        report = self.session.get(DailyReportRecord, report_id) if report_id else None
        summary = (
            dict(report.generation_summary)
            if report is not None and isinstance(report.generation_summary, dict)
            else {}
        )
        return _chinese_enrichment_view(summary)[0]

    def _coverage(
        self,
        run: DailyAutopilotRunRecord,
        event_operation: DailyAutopilotOperationView | None,
    ) -> DailyAutopilotCoverageView:
        metrics = event_operation.metrics if event_operation is not None else {}
        planned = _safe_count(metrics.get("member_total"))
        if planned is None and isinstance(run.requested_scope, dict):
            wave_plan = run.requested_scope.get("wave_plan")
            members = wave_plan.get("members") if isinstance(wave_plan, dict) else None
            planned = len(members) if isinstance(members, list) else None
        succeeded = _safe_count(metrics.get("fetch_succeeded"))
        blocked = _safe_count(metrics.get("blocked"))
        if blocked is None and planned is not None and succeeded is not None:
            blocked = max(planned - succeeded, 0)
        events = _safe_count(metrics.get("event_manifest_count"))

        report = (
            self.session.get(DailyReportRecord, run.daily_report_id)
            if run.daily_report_id
            else None
        )
        summary = (
            report.generation_summary
            if report is not None and isinstance(report.generation_summary, dict)
            else {}
        )
        confirmed = _safe_count(summary.get("confirmed_count"))
        emerging = _safe_count(summary.get("emerging_count"))
        decision_items = (
            confirmed + emerging if confirmed is not None and emerging is not None else None
        )
        overview_items = _safe_count(summary.get("overview_count"))
        omitted = (
            max(events - overview_items, 0)
            if events is not None and overview_items is not None
            else None
        )
        return DailyAutopilotCoverageView(
            planned_targets=planned,
            fetch_succeeded=succeeded,
            blocked_targets=blocked,
            formed_events=events,
            decision_items=decision_items,
            overview_items=overview_items,
            omitted_from_overview=omitted,
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
            metrics=self._collection_metrics(row),
        )

    def _collection_metrics(self, operation: OperationRunRecord) -> dict[str, int]:
        summary = operation.result_summary if isinstance(operation.result_summary, dict) else {}
        keys = (
            "member_total",
            "fetch_succeeded",
            "blocked",
            "failed",
            "partial",
            "event_manifest_count",
            "confirmed_event_count",
        )
        metrics = {
            key: value
            for key in keys
            if (value := _safe_count(summary.get(key))) is not None
        }
        fetch_runs = tuple(
            self.session.scalars(
                select(FetchRunRecord).where(
                    FetchRunRecord.operation_run_id == operation.id
                )
            )
        )
        metrics.update(
            {
                "fetch_run_count": len(fetch_runs),
                "items_received": sum(_database_count(row.items_received) for row in fetch_runs),
                "items_inserted": sum(_database_count(row.items_inserted) for row in fetch_runs),
                "items_updated": sum(_database_count(row.items_updated) for row in fetch_runs),
                "items_unchanged": sum(_database_count(row.items_unchanged) for row in fetch_runs),
            }
        )
        return metrics


def _safe_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _database_count(value: int | None) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _next_action(
    run: DailyAutopilotRunRecord,
    content: DailyAutopilotOperationView | None,
) -> str:
    summary = run.result_summary if isinstance(run.result_summary, dict) else {}
    if run.status == "failed":
        return "请先按上方中文诊断处理；修复后重新开始一次自动日报。"
    if summary.get("outcome") == "audio_partial":
        return _audio_partial_next_action(summary)
    if summary.get("outcome") == "no_content":
        return "本次已完成真实抓取，但没有形成可收录事件；无需把目录探测结果补成新闻。"
    if run.status == "succeeded":
        return "自动日报已完成，可打开中文日报查看两版内容和音频。"
    if content is not None and content.status == "partial":
        return "部分目标受阻；已有真实内容和完整事件时会继续生成中文日报。"
    if run.stage in {"generate_report", "write_reviews"}:
        return "真实内容已就绪，正在生成并审核决策简报与情报全览。"
    if run.stage in {"archive_and_enqueue_audio", "wait_audio"}:
        return "两版报告已完成审核，正在生成决策版与全览版语音。"
    return "任务会在 Worker 中继续推进；单个来源失败不会阻塞整批。"


def _audio_partial_message(summary: dict[str, object]) -> str | None:
    if summary.get("outcome") != "audio_partial":
        return None
    failed = _failed_audio_renditions(summary)
    if failed == {"decision"}:
        return "日报内容已完成，决策版语音失败"
    if failed == {"overview"}:
        return "日报内容已完成，情报全览语音失败"
    if failed == {"decision", "overview"}:
        return "日报内容已完成，决策版语音和情报全览语音失败"
    return "日报内容已完成，部分语音生成失败"


def _audio_partial_next_action(summary: dict[str, object]) -> str:
    failed = _failed_audio_renditions(summary)
    if failed == {"decision"}:
        return "日报内容已完成，请重新生成决策版语音。"
    if failed == {"overview"}:
        return "日报内容已完成，请重新生成全览版语音。"
    return "日报内容已完成，请重新生成缺失的语音版本。"


def _failed_audio_renditions(summary: dict[str, object]) -> set[str]:
    return {
        rendition
        for rendition in ("decision", "overview")
        if summary.get(f"{rendition}_audio_status") == "failed"
    }
