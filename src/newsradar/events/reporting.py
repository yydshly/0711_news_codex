"""Read-only, secret-free Chinese acceptance reporting for Event Intelligence v2."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from re import fullmatch

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import EventScoreRecord, EventVersionRecord, OperationRunRecord
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS

_MAX_WINDOW_HOURS = 720
_MAX_EVENT_IDS = 10_000
_MAX_SUMMARY_COUNT = 1_000_000_000
_MAX_CODE_COUNTS = 100
_SAFE_CODE = r"[a-z][a-z0-9_]{0,63}"
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
    "event_snapshot_incomplete": "Operation 输出事件缺少完整的历史版本快照。",
    "no_input": "当前快照没有输入 RawItem，不能声明处理覆盖完成。",
    "operation_snapshot_invalid": "Operation 结果快照缺失或结构无效。",
    "coverage_incomplete": "Operation 快照中的 relevance-v2 结论未覆盖全部输入。",
    "no_current_events": "本次 Operation 没有可展示的 current 事件。",
    "no_score_snapshots": "本次 current 事件没有合法 score-v2 评分快照。",
    "score_snapshot_incomplete": "部分 current 事件缺少完整、合法的 score-v2 快照。",
    "model_fallback_present": "存在 MiniMax 降级；规则管线已继续完成。",
    "no_minimax_success": "本次 Operation 没有 MiniMax 成功记录。",
    "model_error_attribution_unavailable": (
        "旧 Operation 未保存模型错误聚合，无法把并发模型记录归因到本次运行。"
    ),
    "latest_pipeline_not_succeeded": "最近一次匹配的事件管线未成功完成。",
}


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
    snapshot_at: datetime | None
    window_hours: int
    selected_count: int
    processed_count: int
    included_count: int
    excluded_count: int
    exclusion_reasons: tuple[tuple[str, int], ...]
    candidate_count: int
    visibility_counts: tuple[tuple[str, int], ...]
    status_counts: tuple[tuple[str, int], ...]
    category_counts: tuple[tuple[str, int], ...]
    score_snapshot_count: int
    score_averages: ScoreAverages
    minimax_success_count: int
    minimax_fallback_count: int
    minimax_error_counts: tuple[tuple[str, int], ...]
    latest_operation_id: int | None
    latest_operation_status: str | None
    remaining_issue_codes: tuple[str, ...]
    newsworthy_count: int = 0
    non_newsworthy_count: int = 0
    newsworthiness_reasons: tuple[tuple[str, int], ...] = ()
    tier_counts: tuple[tuple[str, int], ...] = ()
    member_distribution: tuple[tuple[str, int], ...] = ()
    independent_root_distribution: tuple[tuple[str, int], ...] = ()
    pair_direct_merge_count: int = 0
    pair_model_merge_count: int = 0
    pair_separate_count: int = 0
    pair_cache_hit_count: int = 0
    pair_model_error_counts: tuple[tuple[str, int], ...] = ()
    minimax_input_tokens: int = 0
    minimax_output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class _OperationFacts:
    selected_count: int = 0
    processed_count: int = 0
    included_count: int = 0
    excluded_count: int = 0
    exclusion_reasons: tuple[tuple[str, int], ...] = ()
    candidate_count: int = 0
    event_ids: tuple[int, ...] = ()
    event_version_snapshots: tuple[tuple[int, int], ...] = ()
    has_event_version_snapshots: bool = False
    model_success_count: int = 0
    model_fallback_count: int = 0
    model_error_counts: tuple[tuple[str, int], ...] = ()
    valid: bool = False
    model_errors_attributable: bool = True
    newsworthy_count: int = 0
    non_newsworthy_count: int = 0
    newsworthiness_reasons: tuple[tuple[str, int], ...] = ()
    pair_direct_merge_count: int = 0
    pair_model_merge_count: int = 0
    pair_separate_count: int = 0
    pair_cache_hit_count: int = 0
    pair_model_error_counts: tuple[tuple[str, int], ...] = ()
    minimax_input_tokens: int = 0
    minimax_output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class _EventSnapshot:
    event_id: int
    version_number: int
    status: str
    category: str
    occurred_at: datetime
    display_tier: str
    member_count: int
    independent_root_count: int


def build_event_quality_report_view(
    session: Session,
    *,
    window_hours: int = 72,
    now: datetime | None = None,
) -> EventQualityReportView:
    """Project one immutable Operation snapshot without invoking downstream work."""
    if not 1 <= window_hours <= _MAX_WINDOW_HOURS:
        raise ValueError(f"window_hours must be between 1 and {_MAX_WINDOW_HOURS}")
    generated_at = _aware_utc(now or datetime.now(UTC))
    operation = _latest_pipeline_operation(session, window_hours, now=generated_at)
    window_end = _operation_window_end(operation, now=generated_at)
    snapshot_at = _operation_completion_at(operation, now=generated_at)
    facts = _operation_facts(operation)
    since = window_end - timedelta(hours=window_hours) if window_end else None

    visibility_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    tier_counts: Counter[str] = Counter()
    member_distribution: Counter[str] = Counter()
    independent_root_distribution: Counter[str] = Counter()
    event_snapshots: tuple[_EventSnapshot, ...] = ()
    event_snapshots_complete = True
    if snapshot_at is not None and facts.event_ids:
        event_snapshots, event_snapshots_complete = _resolve_event_snapshots(
            session, facts, snapshot_at=snapshot_at
        )
    current_snapshots: list[_EventSnapshot] = []
    if since is not None and window_end is not None:
        for event in event_snapshots:
            if not since <= event.occurred_at <= window_end:
                continue
            visibility_counts["current"] += 1
            status_counts[event.status] += 1
            category_counts[event.category] += 1
            tier_counts[event.display_tier] += 1
            member_distribution[
                "multi_member" if event.member_count > 1 else "single_member"
            ] += 1
            if event.independent_root_count >= 2:
                independent_root_distribution["two_or_more"] += 1
            elif event.independent_root_count == 1:
                independent_root_distribution["one"] += 1
            else:
                independent_root_distribution["none"] += 1
            current_snapshots.append(event)

    valid_scores: dict[int, tuple[float, ...]] = {}
    if current_snapshots and snapshot_at is not None:
        expected_versions = {
            event.event_id: event.version_number for event in current_snapshots
        }
        statement = (
            select(EventScoreRecord)
            .where(
                EventScoreRecord.event_id.in_(expected_versions),
                EventScoreRecord.created_at <= snapshot_at,
            )
            .order_by(
                EventScoreRecord.event_id,
                EventScoreRecord.created_at.desc(),
                EventScoreRecord.id.desc(),
            )
            .execution_options(yield_per=200)
        )
        seen_event_ids: set[int] = set()
        for score in session.scalars(statement):
            if score.version_number != expected_versions.get(score.event_id):
                continue
            if score.event_id in seen_event_ids:
                continue
            seen_event_ids.add(score.event_id)
            values = _valid_score_values(score.breakdown)
            if values is not None:
                valid_scores[score.event_id] = values
    score_averages = ScoreAverages(
        **{
            field: (
                round(sum(values[index] for values in valid_scores.values()) / len(valid_scores), 1)
                if valid_scores
                else 0.0
            )
            for index, field in enumerate(_SCORE_FIELDS)
        }
    )

    issues: list[str] = []
    if operation is None or window_end is None or snapshot_at is None or not facts.valid:
        issues.append("operation_snapshot_invalid")
    if facts.event_ids and not event_snapshots_complete:
        issues.append("event_snapshot_incomplete")
    if facts.selected_count == 0:
        issues.append("no_input")
    if facts.included_count + facts.excluded_count != facts.selected_count:
        issues.append("coverage_incomplete")
    if not current_snapshots:
        issues.append("no_current_events")
    if current_snapshots and not valid_scores:
        issues.append("no_score_snapshots")
    elif len(valid_scores) < len(current_snapshots):
        issues.append("score_snapshot_incomplete")
    if facts.model_fallback_count:
        issues.append("model_fallback_present")
    if facts.candidate_count and not facts.model_success_count:
        issues.append("no_minimax_success")
    if not facts.model_errors_attributable:
        issues.append("model_error_attribution_unavailable")
    if operation is None or operation.status != "succeeded":
        issues.append("latest_pipeline_not_succeeded")

    return EventQualityReportView(
        generated_at=generated_at,
        snapshot_at=snapshot_at,
        window_hours=window_hours,
        selected_count=facts.selected_count,
        processed_count=facts.processed_count,
        included_count=facts.included_count,
        excluded_count=facts.excluded_count,
        exclusion_reasons=facts.exclusion_reasons,
        candidate_count=facts.candidate_count,
        visibility_counts=tuple(sorted(visibility_counts.items())),
        status_counts=tuple(sorted(status_counts.items())),
        category_counts=tuple(sorted(category_counts.items())),
        score_snapshot_count=len(valid_scores),
        score_averages=score_averages,
        minimax_success_count=facts.model_success_count,
        minimax_fallback_count=facts.model_fallback_count,
        minimax_error_counts=facts.model_error_counts,
        latest_operation_id=operation.id if operation else None,
        latest_operation_status=operation.status if operation else None,
        remaining_issue_codes=tuple(dict.fromkeys(issues)),
        newsworthy_count=facts.newsworthy_count,
        non_newsworthy_count=facts.non_newsworthy_count,
        newsworthiness_reasons=facts.newsworthiness_reasons,
        tier_counts=tuple(sorted(tier_counts.items())),
        member_distribution=tuple(sorted(member_distribution.items())),
        independent_root_distribution=tuple(sorted(independent_root_distribution.items())),
        pair_direct_merge_count=facts.pair_direct_merge_count,
        pair_model_merge_count=facts.pair_model_merge_count,
        pair_separate_count=facts.pair_separate_count,
        pair_cache_hit_count=facts.pair_cache_hit_count,
        pair_model_error_counts=facts.pair_model_error_counts,
        minimax_input_tokens=facts.minimax_input_tokens,
        minimax_output_tokens=facts.minimax_output_tokens,
    )


def render_event_quality_report(view: EventQualityReportView) -> str:
    """Render only allow-listed labels, numeric facts, and stable safe codes."""
    conclusion_count = view.included_count + view.excluded_count
    coverage = (
        100 * conclusion_count / view.selected_count if view.selected_count else 0.0
    )
    snapshot_label = (
        _aware_utc(view.snapshot_at).isoformat() if view.snapshot_at else "无可用快照"
    )
    visibility = dict(_safe_counts(view.visibility_counts, {"current", "legacy"}))
    lines = [
        "# Event Intelligence v2.1 事件质量验收报告",
        "",
        f"生成时间：{_aware_utc(view.generated_at).isoformat()}",
        f"Operation 完成快照时间：{snapshot_label}",
        f"统计窗口：Operation 请求窗口末端前 {view.window_hours} 小时 RawItem（含上下界）",
        "",
        "## 输入与处理结论",
        "",
        f"- {view.window_hours} 小时 RawItem：{view.selected_count}",
        f"- 已形成 relevance-v2 唯一结论：{conclusion_count}",
        f"- 进入候选处理：{view.processed_count}",
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
        lines.append("- Operation 快照没有排除原因记录。")
    tier_counts = dict(
        _safe_counts(view.tier_counts, {"hotspot", "signal", "audit_only"})
    )
    member_counts = dict(
        _safe_counts(view.member_distribution, {"single_member", "multi_member"})
    )
    root_counts = dict(
        _safe_counts(
            view.independent_root_distribution, {"none", "one", "two_or_more"}
        )
    )
    lines.extend(
        [
            "",
            "## 新闻价值覆盖",
            "",
            f"- 有新闻价值：{view.newsworthy_count}",
            f"- 无新闻动作或价值不足：{view.non_newsworthy_count}",
            *[
                f"- 新闻价值排除原因 {code}：{count}"
                for code, count in view.newsworthiness_reasons
                if fullmatch(_SAFE_CODE, code)
            ],
            "",
            "## 本次 Operation 候选与事件",
            "",
            f"- 候选簇（cluster-v2）：{view.candidate_count}",
            f"- current：{visibility.get('current', 0)}",
            f"- legacy：{visibility.get('legacy', 0)}",
            f"- 热点：{tier_counts.get('hotspot', 0)}",
            f"- 新兴线索：{tier_counts.get('signal', 0)}",
            f"- 仅审计：{tier_counts.get('audit_only', 0)}",
            f"- 单成员事件：{member_counts.get('single_member', 0)}",
            f"- 多成员事件：{member_counts.get('multi_member', 0)}",
            f"- 无独立证据根：{root_counts.get('none', 0)}",
            f"- 一个独立证据根：{root_counts.get('one', 0)}",
            f"- 两个及以上独立证据根：{root_counts.get('two_or_more', 0)}",
            *[
                f"- 状态 {label}：{count}"
                for label, count in _safe_counts(
                    view.status_counts,
                    {"confirmed", "emerging", "developing", "disputed", "stale", "rejected"},
                )
            ],
            *[
                f"- 分类 {label}：{count}"
                for label, count in _safe_counts(
                    view.category_counts,
                    {"product_model", "research", "developer_tool", "company", "uncategorized"},
                )
            ],
            "",
            "## 本次 current 事件六项平均评分",
            "",
            f"合法 score-v2 快照：{view.score_snapshot_count}",
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
            f"- 匹配的 event_pipeline Operation：{view.latest_operation_id or '无'}",
            f"- Operation 终态：{_safe_status(view.latest_operation_status)}",
            f"- 规则直接合并：{view.pair_direct_merge_count}",
            f"- 模型辅助合并：{view.pair_model_merge_count}",
            f"- 明确分开：{view.pair_separate_count}",
            f"- 候选对缓存命中：{view.pair_cache_hit_count}",
            f"- MiniMax 成功：{view.minimax_success_count}",
            f"- MiniMax 降级：{view.minimax_fallback_count}",
            f"- 输入 token：{view.minimax_input_tokens}",
            f"- 输出 token：{view.minimax_output_tokens}",
        ]
    )
    for code, count in view.pair_model_error_counts:
        label = code if fullmatch(_SAFE_CODE, code) else "未知安全错误码"
        lines.append(f"- 候选对模型错误码 {label}：{count}")
    for code, count in view.minimax_error_counts:
        label = code if fullmatch(_SAFE_CODE, code) else "未知安全错误码"
        lines.append(f"- Operation 模型错误码 {label}：{count}")
    lines.extend(["", "## 剩余问题", ""])
    if view.remaining_issue_codes:
        lines.extend(
            f"- {_ISSUE_LABELS.get(code, '存在未分类问题（内容已隐藏）')}"
            if fullmatch(_SAFE_CODE, code)
            else "- 存在未分类问题（内容已隐藏）"
            for code in view.remaining_issue_codes
        )
    else:
        lines.append("- 当前 Operation 验收口径未发现阻塞问题。")
    lines.extend(
        [
            "",
            "> 本报告为数据库只读投影；不触发抓取、事件构建或模型调用，"
            "且不输出连接串、凭据、原始错误或带查询参数的 URL。",
            "",
        ]
    )
    return "\n".join(lines)


def _latest_pipeline_operation(
    session: Session, window_hours: int, *, now: datetime
) -> OperationRunRecord | None:
    statement = (
        select(OperationRunRecord)
        .where(
            OperationRunRecord.operation_type == "event_pipeline",
            OperationRunRecord.created_at <= now,
        )
        .order_by(OperationRunRecord.id.desc())
        .execution_options(yield_per=100)
    )
    versions = dict(EVENT_ALGORITHM_VERSIONS)
    for operation in session.scalars(statement):
        scope = operation.requested_scope
        scope_window = scope.get("window_hours") if isinstance(scope, dict) else None
        if (
            isinstance(scope, dict)
            and isinstance(scope_window, int)
            and not isinstance(scope_window, bool)
            and scope_window == window_hours
            and scope.get("algorithm_versions") == versions
        ):
            return operation
    return None


def _operation_window_end(
    operation: OperationRunRecord | None, *, now: datetime
) -> datetime | None:
    if operation is None or not isinstance(operation.requested_scope, dict):
        return None
    value = operation.requested_scope.get("window_end")
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = _aware_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None
    return parsed if parsed <= now else None


def _operation_completion_at(
    operation: OperationRunRecord | None, *, now: datetime
) -> datetime | None:
    if operation is None or operation.finished_at is None:
        return None
    finished_at = _aware_utc(operation.finished_at)
    return finished_at if finished_at <= now else None


def _resolve_event_snapshots(
    session: Session,
    facts: _OperationFacts,
    *,
    snapshot_at: datetime,
) -> tuple[tuple[_EventSnapshot, ...], bool]:
    requested_versions: dict[int, int]
    if facts.has_event_version_snapshots:
        requested_versions = dict(facts.event_version_snapshots)
        if len(requested_versions) != len(facts.event_ids):
            return (), False
    else:
        requested_versions = {}

    statement = (
        select(EventVersionRecord)
        .where(
            EventVersionRecord.event_id.in_(facts.event_ids),
            EventVersionRecord.created_at <= snapshot_at,
        )
        .order_by(
            EventVersionRecord.event_id,
            EventVersionRecord.created_at.desc(),
            EventVersionRecord.version_number.desc(),
            EventVersionRecord.id.desc(),
        )
        .execution_options(yield_per=200)
    )
    selected: dict[int, EventVersionRecord] = {}
    for version in session.scalars(statement):
        if version.event_id in selected:
            continue
        requested_version = requested_versions.get(version.event_id)
        if requested_version is not None and version.version_number != requested_version:
            continue
        selected[version.event_id] = version

    snapshots: list[_EventSnapshot] = []
    for event_id in facts.event_ids:
        version = selected.get(event_id)
        if version is None:
            continue
        safe_payload = _safe_event_version_payload(version.payload)
        if safe_payload is None:
            continue
        (
            status,
            category,
            occurred_at,
            display_tier,
            member_count,
            independent_root_count,
        ) = safe_payload
        snapshots.append(
            _EventSnapshot(
                event_id=event_id,
                version_number=version.version_number,
                status=status,
                category=category,
                occurred_at=occurred_at,
                display_tier=display_tier,
                member_count=member_count,
                independent_root_count=independent_root_count,
            )
        )
    return tuple(snapshots), len(snapshots) == len(facts.event_ids)


def _safe_event_version_payload(
    payload: object,
) -> tuple[str, str, datetime, str, int, int] | None:
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if status not in {
        "confirmed",
        "emerging",
        "developing",
        "disputed",
        "stale",
        "rejected",
    }:
        return None
    category = payload.get("category")
    if category is None:
        category = "uncategorized"
    if category not in {
        "product_model",
        "research",
        "developer_tool",
        "company",
        "uncategorized",
    }:
        return None
    occurred_at = payload.get("occurred_at")
    if isinstance(occurred_at, datetime):
        parsed_occurred_at = _aware_utc(occurred_at)
    elif isinstance(occurred_at, str) and len(occurred_at) <= 64:
        try:
            parsed_occurred_at = _aware_utc(
                datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
            )
        except ValueError:
            return None
    else:
        return None
    publication = payload.get("publication")
    display_tier = (
        publication.get("tier") if isinstance(publication, dict) else "signal"
    )
    if display_tier not in {"hotspot", "signal", "audit_only"}:
        return None
    source_item_ids = payload.get("source_item_ids", [])
    if not isinstance(source_item_ids, list) or len(source_item_ids) > _MAX_EVENT_IDS:
        return None
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in source_item_ids
    ):
        return None
    evidence = payload.get("evidence", [])
    if not isinstance(evidence, list) or len(evidence) > _MAX_EVENT_IDS:
        return None
    independent_roots: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            return None
        root = item.get("root_evidence_key")
        independent = item.get("independent")
        if independent is True and isinstance(root, str) and 0 < len(root) <= 1_000:
            independent_roots.add(root)
    return (
        status,
        category,
        parsed_occurred_at,
        display_tier,
        len(set(source_item_ids)),
        len(independent_roots),
    )


def _operation_facts(operation: OperationRunRecord | None) -> _OperationFacts:
    summary = operation.result_summary if operation else None
    if not isinstance(summary, dict):
        return _OperationFacts()
    counts: dict[str, int] = {}
    valid = True
    for key in (
        "selected_item_count",
        "processed_item_count",
        "included_item_count",
        "excluded_item_count",
        "candidate_count",
        "model_success_count",
        "model_fallback_count",
    ):
        value = _safe_count(summary.get(key))
        if value is None:
            valid = False
            value = 0
        counts[key] = value
    reasons = _safe_code_counts(summary.get("exclusion_reasons"))
    if reasons is None:
        valid = False
        reasons = ()
    event_ids = _safe_event_ids(summary.get("event_ids"))
    if event_ids is None:
        valid = False
        event_ids = ()
    raw_event_version_snapshots = summary.get("event_version_snapshots")
    has_event_version_snapshots = raw_event_version_snapshots is not None
    if has_event_version_snapshots:
        event_version_snapshots = _safe_event_version_snapshots(
            raw_event_version_snapshots, event_ids
        )
        if event_version_snapshots is None:
            valid = False
            event_version_snapshots = ()
    else:
        event_version_snapshots = ()
    raw_error_counts = summary.get("model_error_counts")
    model_errors_attributable = True
    if raw_error_counts is None:
        if counts["model_fallback_count"]:
            error_counts = (
                ("error_attribution_unavailable", counts["model_fallback_count"]),
            )
            model_errors_attributable = False
        else:
            error_counts = ()
    else:
        error_counts = _safe_code_counts(raw_error_counts)
        if error_counts is None:
            valid = False
            error_counts = ()
    optional_counts: dict[str, int] = {}
    for key in (
        "newsworthy_item_count",
        "non_newsworthy_item_count",
        "pair_direct_merge_count",
        "pair_model_merge_count",
        "pair_separate_count",
        "pair_cache_hit_count",
        "model_input_tokens",
        "model_output_tokens",
    ):
        value = _safe_count(summary.get(key, 0))
        if value is None:
            valid = False
            value = 0
        optional_counts[key] = value
    newsworthiness_reasons = _safe_code_counts(
        summary.get("newsworthiness_reasons", {})
    )
    if newsworthiness_reasons is None:
        valid = False
        newsworthiness_reasons = ()
    pair_model_error_counts = _safe_code_counts(
        summary.get("pair_model_error_counts", {})
    )
    if pair_model_error_counts is None:
        valid = False
        pair_model_error_counts = ()
    return _OperationFacts(
        selected_count=counts["selected_item_count"],
        processed_count=counts["processed_item_count"],
        included_count=counts["included_item_count"],
        excluded_count=counts["excluded_item_count"],
        exclusion_reasons=reasons,
        candidate_count=counts["candidate_count"],
        event_ids=event_ids,
        event_version_snapshots=event_version_snapshots,
        has_event_version_snapshots=has_event_version_snapshots,
        model_success_count=counts["model_success_count"],
        model_fallback_count=counts["model_fallback_count"],
        model_error_counts=error_counts,
        valid=valid,
        model_errors_attributable=model_errors_attributable,
        newsworthy_count=optional_counts["newsworthy_item_count"],
        non_newsworthy_count=optional_counts["non_newsworthy_item_count"],
        newsworthiness_reasons=newsworthiness_reasons,
        pair_direct_merge_count=optional_counts["pair_direct_merge_count"],
        pair_model_merge_count=optional_counts["pair_model_merge_count"],
        pair_separate_count=optional_counts["pair_separate_count"],
        pair_cache_hit_count=optional_counts["pair_cache_hit_count"],
        pair_model_error_counts=pair_model_error_counts,
        minimax_input_tokens=optional_counts["model_input_tokens"],
        minimax_output_tokens=optional_counts["model_output_tokens"],
    )


def _safe_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= _MAX_SUMMARY_COUNT else None


def _safe_event_ids(value: object) -> tuple[int, ...] | None:
    if not isinstance(value, list) or len(value) > _MAX_EVENT_IDS:
        return None
    if any(
        isinstance(event_id, bool)
        or not isinstance(event_id, int)
        or not 1 <= event_id <= 9_223_372_036_854_775_807
        for event_id in value
    ):
        return None
    unique = tuple(dict.fromkeys(value))
    return unique if len(unique) == len(value) else None


def _safe_event_version_snapshots(
    value: object, event_ids: tuple[int, ...]
) -> tuple[tuple[int, int], ...] | None:
    if not isinstance(value, list) or len(value) > _MAX_EVENT_IDS:
        return None
    snapshots: list[tuple[int, int]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"event_id", "version_number"}:
            return None
        event_id = item.get("event_id")
        version_number = item.get("version_number")
        if (
            isinstance(event_id, bool)
            or not isinstance(event_id, int)
            or event_id <= 0
            or isinstance(version_number, bool)
            or not isinstance(version_number, int)
            or version_number <= 0
        ):
            return None
        snapshots.append((event_id, version_number))
    unique = tuple(dict.fromkeys(snapshots))
    if len(unique) != len(snapshots):
        return None
    if len(unique) != len(event_ids) or {event_id for event_id, _ in unique} != set(event_ids):
        return None
    return unique


def _safe_code_counts(value: object) -> tuple[tuple[str, int], ...] | None:
    if not isinstance(value, dict) or len(value) > _MAX_CODE_COUNTS:
        return None
    result: list[tuple[str, int]] = []
    for code, raw_count in value.items():
        count = _safe_count(raw_count)
        if not isinstance(code, str) or not fullmatch(_SAFE_CODE, code) or count is None:
            return None
        result.append((code, count))
    return tuple(sorted(result, key=lambda item: (-item[1], item[0])))


def _valid_score_values(value: object) -> tuple[float, ...] | None:
    if not isinstance(value, dict) or value.get("rule_version") != "score-v2":
        return None
    result: list[float] = []
    for field in _SCORE_FIELDS:
        raw = value.get(field)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        number = float(raw)
        if not isfinite(number) or not 0 <= number <= 100:
            return None
        result.append(number)
    return tuple(result)


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
