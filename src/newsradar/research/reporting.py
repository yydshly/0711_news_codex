from __future__ import annotations

from newsradar.research.audit import ResearchAuditReport

_STATUS_NAMES = {
    "verified": "已验证",
    "needs_research": "待研究",
    "placeholder": "占位",
    "duplicate": "重复",
    "retired": "退役",
}
_METHOD_NAMES = {
    "rss": "RSS",
    "atom": "Atom",
    "websub": "WebSub",
    "public_api": "公开 API",
    "api_key_api": "API Key API",
    "oauth_api": "OAuth API",
    "sitemap": "站点地图",
    "html": "HTML",
    "json_ld": "JSON-LD",
    "embedded_json": "嵌入式 JSON",
    "library": "第三方库",
    "aggregator": "聚合方法",
    "manual": "人工方式",
}
_DECISION_NAMES = {
    "primary": "首选",
    "supplement": "补充",
    "fallback": "备选",
    "manual_only": "仅人工",
    "rejected": "拒绝",
}
_SAMPLE_STATUS_NAMES = {
    "not_run": "未运行",
    "succeeded": "成功",
    "partial": "部分成功",
    "blocked": "受阻",
    "failed": "失败",
}
_SEVERITY_NAMES = {"error": "错误", "warning": "警告", "info": "提示"}


def render_research_report(report: ResearchAuditReport) -> str:
    """将只读审计结果渲染为中文 Markdown。"""
    lines = ["# 来源研究审计报告", "", "## 汇总", "", "| 指标 | 数量 |", "| --- | ---: |"]
    lines.extend(
        (f"| Provider 总数 | {report.provider_count} |", f"| 真实 Target | {report.target_count} |")
    )
    for status in ("placeholder", "duplicate", "retired", "needs_research", "verified"):
        lines.append(f"| {_STATUS_NAMES[status]} | {report.status_counts.get(status, 0)} |")
    lines.extend(["", "## 候选方式统计", "", "| 方式 | 数量 |", "| --- | ---: |"])
    if report.method_counts:
        lines.extend(
            f"| {_METHOD_NAMES.get(method, method)} | {count} |"
            for method, count in report.method_counts.items()
        )
    else:
        lines.append("| 暂无候选方式 | 0 |")
    lines.extend(["", "## Target 研究明细", ""])
    findings_by_source: dict[str, list[str]] = {}
    for finding in report.findings:
        if finding.source_id and finding.severity in {"error", "warning"}:
            findings_by_source.setdefault(finding.source_id, []).append(finding.message_zh)
    for source in sorted(report.targets, key=lambda item: item.id):
        incomplete = findings_by_source.get(source.id, [])
        if not incomplete and source.status == "needs_research":
            incomplete = ["待补充研究"]
        lines.extend(
            (
                f"### {source.name}（`{source.id}`）",
                "",
                f"- 状态：{_STATUS_NAMES[source.status]}",
                f"- 用途：{source.purpose or '未填写'}",
                f"- 所需信息：{'、'.join(source.wanted_information) or '未填写'}",
                f"- 风险：{source.risk_conclusion or '未填写'}",
                f"- 未完成项：{'；'.join(incomplete) or '无'}",
            )
        )
        if source.candidates:
            lines.extend(
                ["", "| 决策 | 方式 | 信息 | 样本 | 限制 |", "| --- | --- | --- | --- | --- |"]
            )
            for candidate in source.candidates:
                decision = _DECISION_NAMES[candidate.decision]
                method = _METHOD_NAMES.get(candidate.kind, candidate.kind)
                fields = "、".join(candidate.fields)
                sample = _SAMPLE_STATUS_NAMES[candidate.sample_status]
                limitations = "；".join(candidate.limitations) or "无"
                lines.append(f"| {decision} | {method} | {fields} | {sample} | {limitations} |")
        lines.append("")
    lines.extend(["## 审计发现", ""])
    if report.findings:
        lines.extend(
            f"- [{_SEVERITY_NAMES[finding.severity]}] `{finding.code}`：{finding.message_zh}"
            f"（{finding.source_id or finding.provider_id or '全局'}）"
            for finding in report.findings
        )
    else:
        lines.append("- 未发现问题。")
    return "\n".join(lines) + "\n"
