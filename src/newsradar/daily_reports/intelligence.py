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


@dataclass(frozen=True, slots=True)
class OverviewReportItem:
    event_id: int
    status: str
    display_tier: str
    rank_score: float
    zh_title: str
    zh_summary: str
    why_it_matters: str
    confirmation_summary: str
    decision: str | None = None
    recommendation: str | None = None
    evidence_assessment: str | None = None


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


def build_overview_script(
    *,
    report_date: date,
    items: Iterable[OverviewReportItem],
) -> str:
    lines = [f"{report_date.isoformat()} News Codex 情报全览。"]
    grouped = {
        "confirmed": [],
        "hotspot": [],
        "signal": [],
    }
    for item in items:
        if item.decision not in {"keep", "needs_evidence"}:
            continue
        section = _overview_section(item)
        if section is not None:
            grouped[section].append(item)
    if not any(grouped.values()):
        return "\n".join((*lines, "暂无可播报的情报事件。"))
    for section, heading in (
        ("confirmed", "已确认事件"),
        ("hotspot", "热点关注"),
        ("signal", "新兴信号"),
    ):
        section_items = sorted(
            grouped[section], key=lambda item: (-item.rank_score, item.event_id)
        )
        if not section_items:
            continue
        lines.append(heading)
        for item in section_items:
            prefix = "尚待进一步确认：" if item.decision == "needs_evidence" else ""
            lines.append(f"{prefix}{item.zh_title}。{item.zh_summary}。")
            if item.why_it_matters:
                lines.append(f"关注理由：{item.why_it_matters}。")
            if item.confirmation_summary:
                lines.append(f"证据状态：{item.confirmation_summary}。")
            recommendation = _text(item.recommendation)
            if recommendation:
                lines.append(f"行动建议：{recommendation}。")
            assessment = _text(item.evidence_assessment)
            if assessment:
                lines.append(f"证据评价：{assessment}。")
    return "\n".join(lines)


def _overview_section(item: OverviewReportItem) -> str | None:
    if item.status == "confirmed":
        return "confirmed"
    if item.display_tier == "hotspot":
        return "hotspot"
    if item.display_tier == "signal":
        return "signal"
    if item.decision in {"keep", "needs_evidence"}:
        return "signal"
    return None


def _snapshot_text(snapshot: dict[str, object], key: str, fallback: str) -> str:
    return _text(snapshot.get(key)) or fallback


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
