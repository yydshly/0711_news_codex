from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from newsradar.web.mixed_source_queries import MixedSourceDashboard, MixedSourceTarget

_OUTCOME_LABELS = {
    "succeeded": "成功",
    "no_change": "无变化",
    "partial": "部分成功",
    "blocked": "阻塞",
    "failed": "失败",
}


def render_mixed_wave_report(dashboard: MixedSourceDashboard) -> str:
    """Render one auditable Chinese report from catalog and runtime evidence."""
    summary = dashboard.summary
    lines = [
        "# News Codex 高价值混合来源健康报告",
        "",
        "> 本报告区分目录登记、直接抓取、间接发现与真实运行证据。",
        "> 社交来源用于发现和热度；新闻事实仍需官方或独立专业媒体确认。",
        "",
        "## 总览",
        "",
        "| 指标 | 数量 |",
        "|---|---:|",
        f"| 目录目标 | {summary.catalog_target_count} |",
        f"| 已同步目标 | {summary.synced_target_count} |",
        f"| 直接抓取 | {summary.direct_ready_count} |",
        f"| 间接发现 | {summary.indirect_ready_count} |",
        f"| 等待凭据或权限 | {summary.blocked_count} |",
        f"| 降级运行 | {summary.degraded_count} |",
        f"| 抓取失败 | {summary.failed_count} |",
        f"| 尚未运行 | {summary.not_run_count} |",
        f"| 连续三轮稳定 | {summary.three_run_stable_count} |",
        "",
    ]
    for group in dashboard.groups:
        lines.extend([f"## {group.label}", ""])
        if not group.targets:
            lines.extend(["尚无已同步目标。", ""])
            continue
        lines.extend(
            [
                "| 目标 | 当前结论 | 接入 | 最近三轮 | 原始条目 | 说明与下一步 |",
                "|---|---|---|---|---:|---|",
            ]
        )
        lines.extend(_target_row(target) for target in group.targets)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _target_row(target: MixedSourceTarget) -> str:
    runs = " / ".join(_OUTCOME_LABELS.get(value, value) for value in target.three_run_outcomes)
    if not runs:
        runs = "尚未运行"
    access = target.access_kind or "未登记"
    safe_url = _safe_url(target.access_url)
    if safe_url:
        access = f"{access}<br>{safe_url}"
    explanation = f"{target.conclusion_zh}<br>下一步：{target.next_action_zh}"
    cells = (
        f"{target.name}<br>`{target.source_id}`",
        target.state_label,
        access,
        runs,
        str(target.raw_item_count),
        explanation,
    )
    return "| " + " | ".join(_escape(cell) for cell in cells) + " |"


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
