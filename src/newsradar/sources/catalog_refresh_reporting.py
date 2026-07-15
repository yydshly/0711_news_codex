"""Chinese, aggregate-only reporting for frozen source catalog refreshes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

_LANE_LABELS = {
    "content": "内容通道",
    "capability": "能力通道",
    "catalog": "目录通道",
}


def summarize_catalog_members(members: Iterable[Any]) -> dict[str, dict[str, int]]:
    """Aggregate frozen members without reading their free-text conclusions."""
    lane_counts: Counter[str] = Counter()
    state_counts: Counter[str] = Counter()
    result_counts: Counter[str] = Counter()
    for member in members:
        lane = str(getattr(member, "lane", "unknown"))
        state = str(getattr(member, "state", "unknown"))
        lane_counts[lane] += 1
        state_counts[state] += 1
        result_code = getattr(member, "result_code", None)
        if result_code:
            result_counts[str(result_code)] += 1
    return {
        "lanes": dict(sorted(lane_counts.items())),
        "states": dict(sorted(state_counts.items())),
        "result_codes": dict(sorted(result_counts.items())),
    }


def render_catalog_sections(
    operation: Any, summary: dict[str, dict[str, int]], members: Iterable[Any]
) -> list[str]:
    """Render fixed-order sections without exposing secrets or response metadata."""
    materialized = tuple(members)
    current = int(getattr(operation, "progress_current", 0) or 0)
    total = getattr(operation, "progress_total", None)
    if total is None:
        total = len(materialized)
    total = int(total)
    scope = getattr(operation, "requested_scope", {}) or {}
    digest = str(scope.get("catalog_digest", "未记录"))
    # Keep lane ordering stable even for an empty batch.
    lane_lines = [
        f"- {_LANE_LABELS[lane]}：{summary['lanes'].get(lane, 0)}"
        for lane in ("content", "capability", "catalog")
    ]
    result_lines = _count_lines(summary["result_codes"], empty="- 暂无结果码")
    evidence = _content_evidence_lines(materialized)
    unlock = _unlock_lines(materialized)
    gaps = _members_with_codes(
        materialized, {"catalog_incomplete", "manual_only", "stale_result"}, "目录缺口"
    )
    failures = _members_with_states(materialized, {"failed", "blocked", "degraded"})
    return [
        "# 来源目录全量刷新报告",
        "",
        "## 批次 ID",
        f"- 操作：{getattr(operation, 'id', '未知')}",
        f"- 状态：{getattr(operation, 'status', '未知')}",
        "",
        "## 目录摘要",
        f"- 摘要：{digest}",
        f"- 冻结成员：{len(materialized)}",
        "",
        "## 完成度",
        f"- {current}/{total}",
        "",
        "## 三条通道",
        *lane_lines,
        "",
        "## 结果码数量",
        *result_lines,
        "",
        "## 内容三轮证据",
        *evidence,
        "",
        "## 能力解锁条件",
        *unlock,
        "",
        "## 目录缺口",
        *gaps,
        "",
        "## 失败成员",
        *failures,
        "",
        "## 安全边界声明",
        "- 本报告仅汇总冻结批次的通道、状态和结果码，不输出密钥、鉴权头、会话信息、"
        "环境变量配置值或响应头。",
        "- 内容抓取只由 Worker 执行；本报告命令不发起网络请求。",
        "",
    ]


def render_catalog_refresh_report(operation: Any, members: Iterable[Any]) -> str:
    materialized = tuple(members)
    summary = summarize_catalog_members(materialized)
    return "\n".join(render_catalog_sections(operation, summary, materialized))


def _count_lines(counts: dict[str, int], *, empty: str) -> list[str]:
    return [f"- {key}：{value}" for key, value in counts.items()] or [empty]


def _content_evidence_lines(members: tuple[Any, ...]) -> list[str]:
    content = [member for member in members if getattr(member, "lane", None) == "content"]
    complete = sum(
        len(getattr(member, "content_probe_run_ids", ()) or ()) >= 3 for member in content
    )
    return [f"- 已完成三轮证据的内容成员：{complete}/{len(content)}"]


def _unlock_lines(members: tuple[Any, ...]) -> list[str]:
    codes = Counter(
        str(member.result_code)
        for member in members
        if getattr(member, "result_code", None)
        in {"missing_credentials", "requires_approval", "requires_payment"}
    )
    labels = {
        "missing_credentials": "补充凭据",
        "requires_approval": "完成平台审批",
        "requires_payment": "开通付费权限",
    }
    lines = [f"- {labels[code]}：{count}" for code, count in sorted(codes.items())]
    return lines or ["- 当前无待解锁项"]


def _members_with_codes(members: tuple[Any, ...], codes: set[str], empty: str) -> list[str]:
    rows = [
        f"- {getattr(member, 'source_id', '未知来源')}：{getattr(member, 'result_code', 'unknown')}"
        for member in members
        if getattr(member, "result_code", None) in codes
    ]
    return rows or [f"- 无{empty}"]


def _members_with_states(members: tuple[Any, ...], states: set[str]) -> list[str]:
    rows = [
        f"- {getattr(member, 'source_id', '未知来源')}：{getattr(member, 'state', 'unknown')}"
        + (f"（{member.result_code}）" if getattr(member, "result_code", None) else "")
        for member in members
        if getattr(member, "state", None) in states
    ]
    return rows or ["- 无"]
