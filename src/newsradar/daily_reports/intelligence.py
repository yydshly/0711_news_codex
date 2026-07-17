from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class DecisionReportItem:
    included: bool
    section: str
    position: int
    snapshot: dict[str, object]
    decision: str | None
    zh_title: str | None
    zh_summary: str | None
    recommendation: str | None
    evidence_assessment: str | None


def build_decision_script(
    *,
    report_date: date,
    items: Iterable[DecisionReportItem],
) -> str:
    lines = [f"{report_date.isoformat()} News Codex 决策日报。"]
    included = sorted(
        (item for item in items if item.included),
        key=lambda item: (item.section != "confirmed", item.position),
    )
    if not included:
        return "\n".join((*lines, "暂无可播报的已收录事件。"))
    for item in included:
        title = _text(item.zh_title) or _snapshot_text(
            item.snapshot, "zh_title", "未命名事件"
        )
        summary = _text(item.zh_summary) or _snapshot_text(
            item.snapshot, "zh_summary", "暂无中文概述"
        )
        prefix = "待补证：" if item.decision == "needs_evidence" else ""
        lines.append(f"{prefix}{title}。{summary}。")
        recommendation = _text(item.recommendation)
        if recommendation:
            lines.append(f"行动建议：{recommendation}。")
        assessment = _text(item.evidence_assessment)
        if assessment:
            lines.append(f"证据评价：{assessment}。")
    return "\n".join(lines)


def _snapshot_text(snapshot: dict[str, object], key: str, fallback: str) -> str:
    return _text(snapshot.get(key)) or fallback


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
