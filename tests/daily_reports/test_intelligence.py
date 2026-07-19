from datetime import date

from newsradar.daily_reports.intelligence import (
    DecisionReportItem,
    OverviewReportItem,
    build_decision_script,
    build_overview_script,
)


def test_decision_script_uses_audited_chinese_content_and_marks_pending_evidence() -> None:
    script = build_decision_script(
        report_date=date(2026, 7, 17),
        items=(
            DecisionReportItem(
                included=True,
                section="confirmed",
                position=1,
                snapshot={"zh_title": "快照标题", "zh_summary": "快照概述"},
                decision="keep",
                zh_title="人工中文标题",
                zh_summary="人工中文概述",
                recommendation="继续关注后续发布。",
                evidence_assessment="已有两条独立证据。",
            ),
            DecisionReportItem(
                included=True,
                section="emerging",
                position=2,
                snapshot={"zh_title": "线索标题", "zh_summary": "线索概述"},
                decision="needs_evidence",
                zh_title="待补证标题",
                zh_summary="待补证概述",
                recommendation="等待第一方来源。",
                evidence_assessment="尚缺第一方证据。",
            ),
        ),
    )

    assert "2026-07-17 News Codex 决策日报" in script
    assert "人工中文标题。人工中文概述。" in script
    assert "待补证：待补证标题。待补证概述。" in script
    assert "行动建议：等待第一方来源。" in script
    assert "证据评价：尚缺第一方证据。" in script


def test_decision_script_excludes_removed_and_duplicate_items() -> None:
    script = build_decision_script(
        report_date=date(2026, 7, 17),
        items=(
            DecisionReportItem(
                included=False,
                section="emerging",
                position=1,
                snapshot={"zh_title": "不应播报", "zh_summary": "不应播报概述"},
                decision="duplicate",
                zh_title="重复项标题",
                zh_summary="重复项概述",
                recommendation="忽略。",
                evidence_assessment="重复。",
            ),
        ),
    )

    assert "重复项标题" not in script
    assert "暂无可播报的已收录事件" in script


def test_overview_script_groups_each_snapshot_event_once() -> None:
    script = build_overview_script(
        report_date=date(2026, 7, 17),
        items=(
            OverviewReportItem(
                event_id=1,
                status="confirmed",
                display_tier="hotspot",
                rank_score=91.0,
                zh_title="已确认发布",
                zh_summary="官方已公布。",
                why_it_matters="影响产品路线。",
                confirmation_summary="已有官方一手来源确认。",
                decision="keep",
            ),
            OverviewReportItem(
                event_id=2,
                status="emerging",
                display_tier="hotspot",
                rank_score=84.0,
                zh_title="热点进展",
                zh_summary="多家媒体正在跟进。",
                why_it_matters="值得立即关注。",
                confirmation_summary="仍待交叉确认。",
                decision="keep",
            ),
            OverviewReportItem(
                event_id=3,
                status="emerging",
                display_tier="signal",
                rank_score=72.0,
                zh_title="新兴信号",
                zh_summary="出现早期线索。",
                why_it_matters="可能影响后续判断。",
                confirmation_summary="仍需补充独立证据。",
                decision="keep",
            ),
        ),
    )

    assert "2026-07-17 News Codex 情报全览" in script
    assert "已确认事件" in script
    assert "热点关注" in script
    assert "新兴信号" in script
    assert script.count("已确认发布") == 1
    assert "影响产品路线" in script


def test_overview_script_only_speaks_reviewed_included_items_and_marks_risk() -> None:
    def item(event_id: int, title: str, decision: str | None) -> OverviewReportItem:
        return OverviewReportItem(
            event_id=event_id,
            status="emerging",
            display_tier="signal",
            rank_score=80 - event_id,
            decision=decision,
            zh_title=title,
            zh_summary=f"{title}概述",
            why_it_matters="影响后续判断。",
            confirmation_summary="当前证据状态。",
            recommendation="继续核验。",
            evidence_assessment="目前只有聚合来源。",
        )

    script = build_overview_script(
        report_date=date(2026, 7, 17),
        items=(
            item(1, "保留事件", "keep"),
            item(2, "待补证事件", "needs_evidence"),
            item(3, "排除事件", "exclude"),
            item(4, "重复事件", "duplicate"),
            item(5, "未审核事件", None),
        ),
    )

    assert "保留事件" in script
    assert "尚待进一步确认：待补证事件" in script
    assert "证据评价：目前只有聚合来源" in script
    assert "行动建议：继续核验" in script
    assert all(
        title not in script for title in ("排除事件", "重复事件", "未审核事件")
    )


def test_overview_script_degrades_included_unknown_tier_to_signal() -> None:
    script = build_overview_script(
        report_date=date(2026, 7, 17),
        items=(
            OverviewReportItem(
                event_id=7,
                status="emerging",
                display_tier="audit_only",
                rank_score=70,
                zh_title="历史保留线索",
                zh_summary="历史层级不兼容。",
                why_it_matters="仍需持续跟踪。",
                confirmation_summary="当前仍待补证。",
                decision="keep",
            ),
        ),
    )

    assert "新兴信号" in script
    assert script.count("历史保留线索") == 1
