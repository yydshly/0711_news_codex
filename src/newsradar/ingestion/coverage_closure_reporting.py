from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from newsradar.ingestion.coverage_closure import (
    CoverageClosureEntry,
    CoverageClosurePlan,
    CoverageClosureState,
)
from newsradar.ingestion.coverage_closure_runtime import ClosureOperation, CoverageEvidence
from newsradar.operations.logging import redact
from newsradar.operations.retry_policy import is_retryable_error

COVERAGE_CLOSURE_V1_BASELINE_SOURCE_IDS = (
    "arxiv-cs-cl",
    "arxiv-cs-lg",
    "cuda-python-releases",
    "gemini-cli-releases",
    "microsoft-research",
    "openai-youtube",
    "qwen3-releases",
    "transformers-releases",
    "universe-cnbc-1",
    "universe-hard-fork-1",
    "universe-import-ai-1",
    "universe-interconnects-1",
    "universe-mit-tech-review-1",
    "universe-techmeme-1",
    "universe-venturebeat-1",
)
_SENSITIVE_REPORT_TEXT = re.compile(
    r"(?i)(authorization|cookie|proxy-authorization)\s*:\s*[^\r\n|]+"
)


@dataclass(frozen=True, slots=True)
class CatalogAdjustment:
    source_id: str
    conclusion: str
    evidence: str
    next_action: str


def render_coverage_closure_report(
    *,
    before: CoverageClosurePlan,
    after: CoverageClosurePlan,
    operations: Sequence[ClosureOperation],
    before_evidence: Sequence[CoverageEvidence],
    after_evidence: Sequence[CoverageEvidence],
    adjustments: Sequence[CatalogAdjustment],
    generated_at: datetime,
) -> str:
    """Render the bounded source-coverage closure evidence without secrets."""
    operations_by_source = {operation.source_id: operation for operation in operations}
    before_evidence_by_source = {item.source_id: item for item in before_evidence}
    after_evidence_by_source = {item.source_id: item for item in after_evidence}
    adjustments_by_source = {item.source_id: item for item in adjustments}
    before_by_source = {item.source_id: item for item in before.entries}
    after_by_source = {item.source_id: item for item in after.entries}

    lines = [
        "# 来源覆盖收口 v1 验收报告",
        "",
        f"- 生成时间：{generated_at.isoformat()}",
        "- 口径：仅统计 availability=ready 且 coverage_mode=direct 的来源。",
        "- 成功口径：FetchRun 为 succeeded 或 no_change。",
        "",
        "## 执行前",
        "",
        "| 范围内 | 已覆盖 | 可入队 | 阻塞 |",
        "| ---: | ---: | ---: | ---: |",
        _plan_counts(before),
        "",
        "## 本轮操作",
        "",
        "| 来源 ID | 操作 ID | 操作状态 | 最近抓取结果 | 错误码 | 可重试 | "
        "本轮新增 RawItem | 下一步 |",
        "| --- | ---: | --- | --- | --- | --- | ---: | --- |",
    ]
    if operations:
        for operation in sorted(operations, key=lambda item: item.source_id):
            after_item = after_evidence_by_source.get(operation.source_id)
            before_item = before_evidence_by_source.get(operation.source_id)
            error_code = after_item.latest_fetch_error_code if after_item else None
            lines.append(
                "| `{source_id}` | {operation_id} | {status} | {outcome} | {error_code} "
                "| {retryable} | {new_items} | {next_action} |".format(
                    source_id=operation.source_id,
                    operation_id=operation.operation_id if operation.operation_id else "—",
                    status=_safe(operation.status or "queued"),
                    outcome=_safe(
                        after_item.latest_fetch_outcome if after_item else "尚无 FetchRun"
                    ),
                    error_code=_safe(error_code or "—"),
                    retryable=_retryable_label(error_code),
                    new_items=_new_items(before_item, after_item),
                    next_action=_next_action(operation.status, error_code),
                )
            )
    else:
        lines.append("| 无 | — | 未创建操作 | — | — | — | 0 | 仅预览，未写入数据库。 |")

    lines.extend(
        [
            "",
            "## 基线 15 项逐项结论",
            "",
            "| 来源 ID | 执行前探测/资格 | 操作证据 | FetchRun 证据 | "
            "本轮新增 RawItem | 最终结论 |",
            "| --- | --- | --- | --- | ---: | --- |",
        ]
    )
    for source_id in COVERAGE_CLOSURE_V1_BASELINE_SOURCE_IDS:
        adjustment = adjustments_by_source.get(source_id)
        before_entry = before_by_source.get(source_id)
        after_entry = after_by_source.get(source_id)
        if before_entry is None and adjustment is None:
            raise ValueError(f"missing_baseline_conclusion:{source_id}")
        operation = operations_by_source.get(source_id)
        before_item = before_evidence_by_source.get(source_id)
        after_item = after_evidence_by_source.get(source_id)
        if adjustment is not None and before_entry is None:
            initial = adjustment.evidence
            conclusion = adjustment.conclusion
        else:
            initial = _entry_label(before_entry)
            conclusion = _entry_label(after_entry) if after_entry else "尚未重算"
        operation_text = (
            f"操作 {operation.operation_id}：{operation.status or 'queued'}"
            if operation and operation.operation_id
            else "未创建操作"
        )
        fetch_text = _fetch_label(after_item)
        baseline_cells = [
            f"`{source_id}`",
            _safe(initial),
            _safe(operation_text),
            _safe(fetch_text),
            str(_new_items(before_item, after_item)),
            _safe(conclusion),
        ]
        lines.append("| " + " | ".join(baseline_cells) + " |")

    lines.extend(
        [
            "",
            "## 执行后",
            "",
            "| 范围内 | 已覆盖 | 可入队 | 阻塞 |",
            "| ---: | ---: | ---: | ---: |",
            _plan_counts(after),
            "",
            "## 仍未收口的来源",
            "",
            "| 来源 ID | 稳定原因码 | 中文说明 |",
            "| --- | --- | --- |",
        ]
    )
    if after.blocked or after.queueable:
        for entry in (*after.queueable, *after.blocked):
            lines.append(
                f"| `{entry.source_id}` | `{entry.code or 'queueable'}` | {_safe(entry.reason)} |"
            )
    else:
        lines.append("| 无 | — | 当前范围内来源均已有成功抓取证据。 |")

    lines.extend(
        [
            "",
            "## 两项目录口径修正",
            "",
            "- OpenAI YouTube：Atom 负责公开发现；engagement 由需 Key 的 Data API 补充，"
            "不阻塞 Atom。",
            "- Qwen3 Releases：当前无 Release 条目，退出 ready 统计；满足解锁条件后重新探测。",
            "",
            "## 安全声明",
            "",
            "- 本轮未使用 Cookie、浏览器会话、代理绕过或 MiniMax 决策。",
            "",
            "## 结论",
            "",
            _conclusion(after),
            "",
        ]
    )
    return "\n".join(lines)


def _plan_counts(plan: CoverageClosurePlan) -> str:
    return (
        f"| {len(plan.entries)} | {len(plan.covered)} | {len(plan.queueable)} "
        f"| {len(plan.blocked)} |"
    )


def _entry_label(entry: CoverageClosureEntry | None) -> str:
    if entry is None:
        return "尚未重算"
    if entry.state is CoverageClosureState.COVERED:
        return "已覆盖：已有 succeeded/no_change 抓取证据。"
    if entry.state is CoverageClosureState.QUEUEABLE:
        return f"可入队：{entry.reason}"
    return f"阻塞（{entry.code or 'unknown'}）：{entry.reason}"


def _fetch_label(evidence: CoverageEvidence | None) -> str:
    if evidence is None or evidence.latest_fetch_outcome is None:
        return "尚无 FetchRun"
    error = (
        f"；错误码 {evidence.latest_fetch_error_code}" if evidence.latest_fetch_error_code else ""
    )
    return f"{evidence.latest_fetch_outcome}{error}"


def _new_items(
    before: CoverageEvidence | None,
    after: CoverageEvidence | None,
) -> int:
    return max((after.raw_item_count if after else 0) - (before.raw_item_count if before else 0), 0)


def _retryable_label(error_code: str | None) -> str:
    if error_code is None:
        return "—"
    return "是" if is_retryable_error(error_code) else "否"


def _next_action(status: str | None, error_code: str | None) -> str:
    if status in {"enqueue_failed", "missing", "timed_out"}:
        return "检查任务运行状态后重新执行。"
    if error_code is None:
        return "无需处理。"
    if is_retryable_error(error_code):
        return "检查网络或限流后重新执行。"
    return "处理权限或目录状态后再执行。"


def _conclusion(plan: CoverageClosurePlan) -> str:
    if not plan.queueable and not plan.blocked:
        return "当前 ready + direct 范围内来源均已留下成功抓取证据。"
    return f"仍有 {len(plan.queueable) + len(plan.blocked)} 个来源需要继续处理，详见上表。"


def _safe(value: object) -> str:
    text = _SENSITIVE_REPORT_TEXT.sub("[REDACTED]", redact(value))
    return text.replace("|", "/").replace("\r", " ").replace("\n", " ")
