"""Scrubbed Chinese acceptance reporting for a frozen high-value news wave."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from newsradar.operations.logging import redact

_SENSITIVE_WORDS = re.compile(r"authorization|cookie|api[_-]?key|token|secret|password", re.I)


def render_high_value_wave_report(
    operation: object,
    members: Iterable[object],
    events: Iterable[Mapping[str, object]],
) -> str:
    """Render facts already persisted by an operation; never request source content."""
    scope = _mapping(getattr(operation, "requested_scope", {}))
    summary = _mapping(getattr(operation, "result_summary", {}))
    rows = list(events)
    confirmed = [row for row in rows if _value(row, "signal_state") == "confirmed"]
    early = [row for row in rows if _value(row, "signal_state") == "early_signal"]
    trends = [row for row in rows if _value(row, "trend") in {"rising", "sustained", "cooling"}]
    member_rows = list(members)
    total = _value(summary, "member_total") or len(member_rows)
    window_hours = _safe(_value(scope, "window_hours") or "-")
    trend_days = _safe(_value(scope, "trend_days") or "-")
    model_mode = "是（规则快照仍可用）" if _value(summary, "model_degraded") else "否或未调用"
    lines = [
        "# 高价值 AI/技术新闻波次验收报告",
        "",
        "## 执行范围",
        "",
        f"- 波次：{_safe(getattr(operation, 'id', '-'))}",
        f"- 状态：{_safe(getattr(operation, 'status', '-'))}",
        f"- Profile：{_safe(_value(scope, 'profile_id') or '-')}",
        f"- 窗口：最近 {window_hours} 小时；趋势 {trend_days} 天",
        f"- 成员完成：{_safe(_value(summary, 'completed_members') or 0)}/{_safe(total)}",
        f"- 模型降级：{model_mode}",
        "",
        "## 证据确认覆盖",
        "",
        f"- 证据型成员：{_count(summary, 'evidence_capable_members')}",
        f"- 直接证据抓取成功：{_count(summary, 'direct_evidence_fetch_succeeded')}",
        f"- 含官方证据根事件：{_count(summary, 'events_with_official_root')}",
        f"- 含一个专业媒体根事件：{_count(summary, 'events_with_one_professional_root')}",
        f"- 含两个专业媒体根事件：{_count(summary, 'events_with_two_professional_roots')}",
        f"- 已确认事件：{_count(summary, 'confirmed_event_count')}",
        f"- 边界候选检查：{_count(summary, 'ambiguous_pairs_checked')}",
        f"- 模型配对保守回退：{_count(summary, 'model_pair_fallback_count')}",
        "",
        "## 已确认热点",
        "",
        *_event_lines(confirmed, empty="本轮没有满足官方或独立媒体证据规则的事件。"),
        "",
        "## 早期信号",
        "",
        *_event_lines(early, empty="本轮信号均已确认，或没有足够的新社区/社交信号。"),
        "",
        "## 7 天趋势",
        "",
        *_event_lines(trends, empty="没有可比较的已持久化趋势快照。"),
        "",
        "## 冻结成员结果",
        "",
        "| 来源 | 平台 | 可抓取 | 状态 | 结果代码 | 说明 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for member in member_rows:
        lines.append(
            "| {source} | {provider} | {fetchable} | {state} | {code} | {conclusion} |".format(
                source=_cell(getattr(member, "source_id", "-")),
                provider=_cell(getattr(member, "provider_id", "-")),
                fetchable="是" if getattr(member, "fetchable", False) else "否",
                state=_cell(getattr(member, "state", "-")),
                code=_cell(getattr(member, "result_code", None) or "-"),
                conclusion=_cell(getattr(member, "conclusion", None) or "-"),
            )
        )
    lines.extend(
        [
            "",
            "## 验收说明",
            "",
            "- 社区、社交和聚合来源只作为发现或热度信号；未满足证据规则时保持在“早期信号”。",
            "- 阻塞成员只记录冻结原因，不触发网页回退、登录态会话或其他绕过方式。",
            "- 本报告只使用已持久化的成员和事件元数据；不包含请求头、正文或凭据。",
        ]
    )
    return "\n".join(lines) + "\n"


def _event_lines(rows: list[Mapping[str, object]], *, empty: str) -> list[str]:
    if not rows:
        return [empty]
    return [
        "- {title}（热度 {heat}；趋势 {trend}；独立证据根 {roots}）".format(
            title=_safe(_value(row, "title") or "未命名事件"),
            heat=_safe(_value(row, "heat") or 0),
            trend=_safe(_value(row, "trend") or "暂无"),
            roots=_safe(_value(row, "evidence_roots") or 0),
        )
        for row in rows
    ]


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _value(value: Mapping[str, object], key: str) -> object:
    return value.get(key)


def _count(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    return item if isinstance(item, int) and not isinstance(item, bool) and item >= 0 else 0


def _cell(value: object) -> str:
    return _safe(value).replace("|", "\\|").replace("\n", " ")


def _safe(value: object) -> str:
    text = redact(value)
    return "已脱敏" if _SENSITIVE_WORDS.search(text) else text
