from datetime import date

from newsradar.daily_reports.intelligence import DecisionReportItem, build_decision_script


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
