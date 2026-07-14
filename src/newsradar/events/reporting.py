"""Read-only, secret-free Chinese acceptance reporting for Event Intelligence v2."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from re import fullmatch

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    EventCandidateRecord,
    EventModelRunRecord,
    EventRecord,
    EventScoreRecord,
    ModelUsageRecord,
    OperationRunRecord,
    RawItemProcessingRecord,
    RawItemRecord,
)
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS

_SCORE_FIELDS = (
    "ai_relevance",
    "source_coverage",
    "source_authority",
    "recency",
    "engagement_velocity",
    "novelty",
)
_SCORE_LABELS = {
    "ai_relevance": "AI 相关性",
    "source_coverage": "来源覆盖",
    "source_authority": "来源权威性",
    "recency": "时效",
    "engagement_velocity": "互动热度",
    "novelty": "新颖性",
}
_REASON_LABELS = {
    "ambiguous_term_only": "仅命中歧义词",
    "game_or_entertainment": "游戏或娱乐内容",
    "advertisement_or_subscription": "广告、促销或订阅引导",
    "generic_technology": "泛科技且无明确 AI 事实",
    "auto_repost_without_claim": "自动转发且缺少事实主张",
    "insufficient_text": "文本信息不足",
}
_ISSUE_LABELS = {
    "coverage_incomplete": "最近窗口仍有 RawItem 缺少 relevance-v2 唯一结论。",
    "no_current_events": "当前尚未发布 current 事件。",
    "no_score_snapshots": "current 事件尚无可用 score-v2 评分快照。",
    "model_fallback_present": "存在 MiniMax 降级；规则管线已继续完成。",
    "no_minimax_success": "当前窗口没有 MiniMax 成功记录。",
    "latest_pipeline_not_succeeded": "最近一次 72 小时事件管线未成功完成。",
}
_SAFE_CODE = r"[a-z][a-z0-9_]{0,63}"


@dataclass(frozen=True, slots=True)
class ScoreAverages:
    ai_relevance: float = 0.0
    source_coverage: float = 0.0
    source_authority: float = 0.0
    recency: float = 0.0
    engagement_velocity: float = 0.0
    novelty: float = 0.0


@dataclass(frozen=True, slots=True)
class EventQualityReportView:
    generated_at: datetime
    window_hours: int
    selected_count: int
    processed_count: int
    included_count: int
    excluded_count: int
    exclusion_reasons: tuple[tuple[str, int], ...]
    candidate_count: int
    visibility_counts: tuple[tuple[str, int], ...]
    status_counts: tuple[tuple[str, int], ...]
    score_snapshot_count: int
    score_averages: ScoreAverages
    minimax_success_count: int
    minimax_fallback_count: int
    minimax_error_counts: tuple[tuple[str, int], ...]
    latest_operation_id: int | None
    latest_operation_status: str | None
    remaining_issue_codes: tuple[str, ...]


def build_event_quality_report_view(
    session: Session,
    *,
    window_hours: int = 72,
    now: datetime | None = None,
) -> EventQualityReportView:
    """Project bounded aggregate facts; never fetch, build events, or call a model."""
    if window_hours <= 0:
        raise ValueError("window_hours must be positive")
    snapshot_now = _aware_utc(now or datetime.now(UTC))
    since = snapshot_now - timedelta(hours=window_hours)
    item_time = func.coalesce(RawItemRecord.published_at, RawItemRecord.fetched_at)
    selected_ids = select(RawItemRecord.id).where(
        item_time >= since,
        item_time <= snapshot_now,
    )
    selected_count = _count(
        session,
        select(func.count(RawItemRecord.id)).where(
            item_time >= since,
            item_time <= snapshot_now,
        ),
    )
    processing_rows = session.execute(
        select(RawItemProcessingRecord.outcome, RawItemProcessingRecord.reason_codes).where(
            RawItemProcessingRecord.raw_item_id.in_(selected_ids),
            RawItemProcessingRecord.stage == "relevance",
            RawItemProcessingRecord.algorithm_version == EVENT_ALGORITHM_VERSIONS["relevance"],
            RawItemProcessingRecord.outcome.in_(("included", "excluded")),
        )
    ).all()
    outcomes = Counter(str(row.outcome) for row in processing_rows)
    reasons: Counter[str] = Counter()
    for row in processing_rows:
        if row.outcome != "excluded" or not isinstance(row.reason_codes, list):
            continue
        reasons.update(
            reason
            for value in row.reason_codes
            if isinstance(value, str) and fullmatch(_SAFE_CODE, reason := value)
        )

    candidate_count = _count(
        session,
        select(func.count(EventCandidateRecord.id)).where(
            EventCandidateRecord.algorithm_version == EVENT_ALGORITHM_VERSIONS["cluster"],
            EventCandidateRecord.updated_at >= since,
            EventCandidateRecord.updated_at <= snapshot_now,
        ),
    )
    visibility_counts = _grouped_counts(session, EventRecord.visibility)
    status_counts = _grouped_counts(
        session,
        EventRecord.status,
        EventRecord.visibility == "current",
        EventRecord.current_version_number > 0,
    )
    score_rows = session.scalars(
        select(EventScoreRecord)
        .join(EventRecord, EventRecord.id == EventScoreRecord.event_id)
        .where(
            EventRecord.visibility == "current",
            EventRecord.current_version_number > 0,
            EventScoreRecord.version_number == EventRecord.current_version_number,
        )
    ).all()
    score_values: dict[str, list[float]] = {field: [] for field in _SCORE_FIELDS}
    for row in score_rows:
        if not isinstance(row.breakdown, dict):
            continue
        for field in _SCORE_FIELDS:
            value = row.breakdown.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            number = float(value)
            if isfinite(number):
                score_values[field].append(min(100.0, max(0.0, number)))
    score_averages = ScoreAverages(
        **{
            field: round(sum(values) / len(values), 1) if values else 0.0
            for field, values in score_values.items()
        }
    )

    operation = _latest_pipeline_operation(
        session,
        window_hours,
        since=since,
        now=snapshot_now,
    )
    usage_since = operation.started_at if operation and operation.started_at else since
    usage_until = operation.finished_at if operation and operation.finished_at else snapshot_now
    usage_rows = session.execute(
        select(ModelUsageRecord.outcome, ModelUsageRecord.error)
        .join(EventModelRunRecord, EventModelRunRecord.model_usage_id == ModelUsageRecord.id)
        .where(
            EventModelRunRecord.created_at >= usage_since,
            EventModelRunRecord.created_at <= usage_until,
        )
    ).all()
    result_summary = (
        operation.result_summary
        if operation and isinstance(operation.result_summary, dict)
        else {}
    )
    summary_success = result_summary.get("model_success_count")
    summary_fallback = result_summary.get("model_fallback_count")
    minimax_success_count = (
        int(summary_success)
        if isinstance(summary_success, int) and not isinstance(summary_success, bool)
        else sum(row.outcome == "success" for row in usage_rows)
    )
    minimax_fallback_count = (
        int(summary_fallback)
        if isinstance(summary_fallback, int) and not isinstance(summary_fallback, bool)
        else sum(row.outcome == "fallback" for row in usage_rows)
    )
    error_counts = Counter(
        error
        for row in usage_rows
        if row.outcome != "success"
        and isinstance(row.error, str)
        and fullmatch(_SAFE_CODE, error := row.error)
    )
    issue_codes: list[str] = []
    if len(processing_rows) != selected_count or sum(outcomes.values()) != selected_count:
        issue_codes.append("coverage_incomplete")
    if dict(visibility_counts).get("current", 0) == 0:
        issue_codes.append("no_current_events")
    if not score_rows:
        issue_codes.append("no_score_snapshots")
    if minimax_fallback_count:
        issue_codes.append("model_fallback_present")
    if not minimax_success_count:
        issue_codes.append("no_minimax_success")
    if operation is None or operation.status != "succeeded":
        issue_codes.append("latest_pipeline_not_succeeded")

    return EventQualityReportView(
        generated_at=snapshot_now,
        window_hours=window_hours,
        selected_count=selected_count,
        processed_count=len(processing_rows),
        included_count=outcomes["included"],
        excluded_count=outcomes["excluded"],
        exclusion_reasons=tuple(sorted(reasons.items(), key=lambda item: (-item[1], item[0]))),
        candidate_count=candidate_count,
        visibility_counts=visibility_counts,
        status_counts=status_counts,
        score_snapshot_count=len(score_rows),
        score_averages=score_averages,
        minimax_success_count=minimax_success_count,
        minimax_fallback_count=minimax_fallback_count,
        minimax_error_counts=tuple(sorted(error_counts.items())),
        latest_operation_id=operation.id if operation else None,
        latest_operation_status=operation.status if operation else None,
        remaining_issue_codes=tuple(issue_codes),
    )


def render_event_quality_report(view: EventQualityReportView) -> str:
    """Render only allow-listed labels, numeric facts, and stable safe codes."""
    coverage = (
        100.0
        if view.selected_count == 0
        else 100 * view.processed_count / view.selected_count
    )
    lines = [
        "# Event Intelligence v2 事件质量验收报告",
        "",
        f"生成时间：{_aware_utc(view.generated_at).isoformat()}",
        f"统计窗口：最近 {view.window_hours} 小时 RawItem（含上界，不读取未来数据）",
        "",
        "## 输入与处理结论",
        "",
        f"- 72 小时 RawItem：{view.selected_count}",
        f"- 已形成 relevance-v2 唯一结论：{view.processed_count}",
        f"- included：{view.included_count}",
        f"- excluded：{view.excluded_count}",
        f"- 规则处理覆盖率：{coverage:.1f}%",
        "",
        "### 排除原因",
        "",
    ]
    if view.exclusion_reasons:
        lines.extend(
            f"- {_safe_reason_label(code)}：{count}"
            for code, count in view.exclusion_reasons
        )
    else:
        lines.append("- 当前窗口没有排除记录。")
    lines.extend(
        [
            "",
            "## 候选与事件",
            "",
            f"- 候选簇（cluster-v2）：{view.candidate_count}",
            *[
                f"- {label}：{count}"
                for label, count in _safe_counts(view.visibility_counts, {"current", "legacy"})
            ],
            *[
                f"- 状态 {label}：{count}"
                for label, count in _safe_counts(
                    view.status_counts,
                    {"confirmed", "emerging", "developing", "disputed", "stale", "rejected"},
                )
            ],
            "",
            "## current 事件六项平均评分",
            "",
            f"评分快照：{view.score_snapshot_count}",
        ]
    )
    lines.extend(
        f"- {_SCORE_LABELS[field]}：{getattr(view.score_averages, field):.1f}"
        for field in _SCORE_FIELDS
    )
    lines.extend(
        [
            "",
            "## Worker 与 MiniMax",
            "",
            f"- 最近 72 小时 event_pipeline Operation：{view.latest_operation_id or '无'}",
            f"- Operation 终态：{_safe_status(view.latest_operation_status)}",
            f"- MiniMax 成功：{view.minimax_success_count}",
            f"- MiniMax 降级：{view.minimax_fallback_count}",
        ]
    )
    for code, count in view.minimax_error_counts:
        label = code if fullmatch(_SAFE_CODE, code) else "未知安全错误码"
        lines.append(f"- 失败尝试错误码 {label}：{count}")
    lines.extend(["", "## 剩余问题", ""])
    if view.remaining_issue_codes:
        lines.extend(
            f"- {_ISSUE_LABELS.get(code, '存在未分类问题（内容已隐藏）')}"
            if fullmatch(_SAFE_CODE, code)
            else "- 存在未分类问题（内容已隐藏）"
            for code in view.remaining_issue_codes
        )
    else:
        lines.append("- 当前验收口径未发现阻塞问题。")
    lines.extend(
        [
            "",
            "> 本报告为数据库只读投影；不触发抓取、事件构建或模型调用，"
            "且不输出连接串、凭据、原始错误或带查询参数的 URL。",
            "",
        ]
    )
    return "\n".join(lines)


def _count(session: Session, statement) -> int:
    return int(session.scalar(statement) or 0)


def _grouped_counts(session: Session, field, *conditions) -> tuple[tuple[str, int], ...]:
    statement = select(field, func.count(EventRecord.id)).group_by(field).order_by(field)
    if conditions:
        statement = statement.where(*conditions)
    return tuple((str(label), int(count)) for label, count in session.execute(statement))


def _latest_pipeline_operation(
    session: Session,
    window_hours: int,
    *,
    since: datetime,
    now: datetime,
) -> OperationRunRecord | None:
    rows = session.scalars(
        select(OperationRunRecord)
        .where(
            OperationRunRecord.operation_type == "event_pipeline",
            OperationRunRecord.created_at >= since,
            OperationRunRecord.created_at <= now,
        )
        .order_by(OperationRunRecord.id.desc())
        .limit(100)
    )
    versions = dict(EVENT_ALGORITHM_VERSIONS)
    return next(
        (
            row
            for row in rows
            if isinstance(row.requested_scope, dict)
            and row.requested_scope.get("window_hours") == window_hours
            and row.requested_scope.get("algorithm_versions") == versions
        ),
        None,
    )


def _safe_counts(
    values: tuple[tuple[str, int], ...], allowed: set[str]
) -> tuple[tuple[str, int], ...]:
    return tuple((label, count) for label, count in values if label in allowed)


def _safe_reason_label(code: str) -> str:
    if not fullmatch(_SAFE_CODE, code):
        return "未知排除原因"
    return _REASON_LABELS.get(code, f"其他规则原因（{code}）")


def _safe_status(status: str | None) -> str:
    if status in {"pending", "running", "succeeded", "partial", "failed", "cancelled"}:
        return str(status)
    return "无可用终态"


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
