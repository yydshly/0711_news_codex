from __future__ import annotations

from collections import Counter
from urllib.parse import urlsplit, urlunsplit

from .schema import RemediationManifest


def render_remediation_report(manifest: RemediationManifest) -> str:
    """Render a public, Chinese report without query, fragment, or credential data."""
    counts = Counter(entry.category.value for entry in manifest.entries)
    lines = [
        "# 来源失败修复报告",
        "",
        f"基线时间：{manifest.baseline_at.isoformat()}",
        f"固定失败 Target 数：{len(manifest.entries)}",
        f"修复前可试用来源：{_count(manifest.before_trial_count)}",
        f"修复后可试用来源：{_count(manifest.after_trial_count)}",
        "",
        "## 分类汇总",
        "",
        "| 分类 | 数量 |",
        "| --- | ---: |",
    ]
    for category, count in sorted(counts.items()):
        lines.append(f"| `{category}` | {count} |")
    lines.extend(
        [
            "",
            "## 固定清单",
            "",
            "| 来源 | 原探测与分类 | 官方候选 | 研究探测 | 内容探测 "
            "| 试用与抓取 | HTML | 最终结论 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for entry in manifest.entries:
        evidence = entry.evidence
        conclusion = (
            evidence.final_conclusion_zh
            if evidence and evidence.final_conclusion_zh
            else entry.next_action_zh
        )
        lines.append(
            f"| {entry.source_name} (`{entry.source_id}`) "
            f"| {entry.original_probe_id} / `{entry.category.value}`；{entry.reason_zh}；"
            f"{_public_url(entry.access_url)} "
            f"| {_candidate(evidence)} | {_acquisition(evidence)} | {_content(evidence)} "
            f"| {_trial_and_fetch(evidence)} | "
            f"{evidence.html_research_status if evidence else '尚无验证证据'} "
            f"| {conclusion} |"
        )
    return "\n".join(lines) + "\n"


def _count(value: int | None) -> str:
    return str(value) if value is not None else "尚未重算"


def _candidate(evidence) -> str:
    if evidence is None or evidence.candidate_key is None:
        return "尚未登记"
    return f"{evidence.candidate_key} / {evidence.candidate_kind or '未知'}"


def _acquisition(evidence) -> str:
    if evidence is None or evidence.acquisition_outcome is None:
        return "尚未运行"
    count = evidence.acquisition_sample_count
    return f"{evidence.acquisition_outcome} / {count if count is not None else 0} 条"


def _content(evidence) -> str:
    if evidence is None or evidence.content_outcome is None:
        return "尚未运行"
    count = evidence.content_sample_count if evidence.content_sample_count is not None else 0
    completeness = (
        f"{evidence.field_completeness:.0%}"
        if evidence.field_completeness is not None
        else "未知"
    )
    return f"{evidence.content_outcome} / {count} 条 / {completeness}"


def _trial_and_fetch(evidence) -> str:
    if evidence is None or evidence.trial_eligible is None:
        return "尚未重算"
    if not evidence.trial_eligible:
        return f"不可试用：{evidence.trial_reason_zh or '条件未满足'}"
    if evidence.fetch_outcome is None:
        return "可试用；尚未抓取"
    received = evidence.fetch_items_received if evidence.fetch_items_received is not None else 0
    inserted = evidence.fetch_items_inserted if evidence.fetch_items_inserted is not None else 0
    return f"可试用；{evidence.fetch_outcome}；接收 {received} / 新增 {inserted}"


def _public_url(value: str | None) -> str:
    if not value:
        return "—"
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
