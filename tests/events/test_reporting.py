from dataclasses import replace
from datetime import UTC, datetime

from newsradar.events.reporting import (
    EventQualityReportView,
    ScoreAverages,
    render_event_quality_report,
)


def sample_quality_view() -> EventQualityReportView:
    return EventQualityReportView(
        generated_at=datetime(2026, 7, 15, 8, 0, tzinfo=UTC),
        snapshot_at=datetime(2026, 7, 15, 7, 0, tzinfo=UTC),
        window_hours=72,
        selected_count=12,
        processed_count=12,
        included_count=5,
        excluded_count=7,
        exclusion_reasons=(("generic_technology", 4), ("insufficient_text", 3)),
        candidate_count=3,
        visibility_counts=(("current", 2), ("legacy", 72)),
        status_counts=(("confirmed", 1), ("emerging", 1)),
        category_counts=(("product_model", 1), ("research", 1)),
        score_snapshot_count=2,
        score_averages=ScoreAverages(
            ai_relevance=88.0,
            source_coverage=52.5,
            source_authority=80.0,
            recency=90.0,
            engagement_velocity=25.0,
            novelty=75.0,
        ),
        minimax_success_count=1,
        minimax_fallback_count=1,
        minimax_error_counts=(("model_timeout", 1),),
        latest_operation_id=321,
        latest_operation_status="succeeded",
        remaining_issue_codes=("model_fallback_present",),
    )


def test_quality_report_is_chinese_auditable_and_secret_free() -> None:
    report = render_event_quality_report(sample_quality_view())

    for expected in (
        "# Event Intelligence v2.1 事件质量验收报告",
        "72 小时 RawItem",
        "included",
        "excluded",
        "排除原因",
        "候选簇",
        "current",
        "legacy",
        "AI 相关性",
        "来源覆盖",
        "来源权威性",
        "时效",
        "互动热度",
        "新颖性",
        "MiniMax 成功",
        "MiniMax 降级",
        "剩余问题",
        "321",
        "Operation 完成快照时间",
    ):
        assert expected in report
    for forbidden in (
        "secret-value",
        "?key=",
        "DATABASE_URL",
        "Authorization",
        "Cookie",
    ):
        assert forbidden not in report


def test_quality_report_never_renders_untrusted_issue_or_error_text() -> None:
    unsafe = replace(
        sample_quality_view(),
        minimax_error_counts=(("https://bad.test/?key=secret-value", 1),),
        remaining_issue_codes=("Authorization: Bearer secret-value",),
    )

    report = render_event_quality_report(unsafe)

    assert "secret-value" not in report
    assert "bad.test" not in report
    assert "Authorization" not in report
    assert "未知安全错误码" in report
    assert "存在未分类问题（内容已隐藏）" in report


def test_empty_report_does_not_claim_complete_coverage() -> None:
    view = replace(
        sample_quality_view(),
        snapshot_at=None,
        selected_count=0,
        processed_count=0,
        included_count=0,
        excluded_count=0,
        candidate_count=0,
        visibility_counts=(),
        status_counts=(),
        score_snapshot_count=0,
        latest_operation_id=None,
        latest_operation_status=None,
        remaining_issue_codes=("no_input",),
    )

    report = render_event_quality_report(view)

    assert "规则处理覆盖率：0.0%" in report
    assert "当前快照没有输入 RawItem" in report


def test_report_always_displays_current_and_legacy_operation_counts() -> None:
    view = replace(sample_quality_view(), visibility_counts=(("current", 2),))

    report = render_event_quality_report(view)

    assert "current：2" in report
    assert "legacy：0" in report


def test_v2_1_report_explains_tiers_membership_pairing_and_tokens() -> None:
    view = replace(
        sample_quality_view(),
        newsworthy_count=5,
        non_newsworthy_count=2,
        newsworthiness_reasons=(("no_event_action", 2),),
        tier_counts=(("audit_only", 1), ("hotspot", 1), ("signal", 1)),
        member_distribution=(("multi_member", 1), ("single_member", 1)),
        independent_root_distribution=(("one", 1), ("two_or_more", 1)),
        pair_direct_merge_count=4,
        pair_model_merge_count=1,
        pair_separate_count=7,
        pair_cache_hit_count=3,
        pair_model_error_counts=(("model_timeout", 1),),
        minimax_input_tokens=1200,
        minimax_output_tokens=240,
    )

    report = render_event_quality_report(view)

    for expected in (
        "新闻价值覆盖",
        "热点：1",
        "新兴线索：1",
        "仅审计：1",
        "单成员事件：1",
        "多成员事件：1",
        "两个及以上独立证据根：1",
        "规则直接合并：4",
        "模型辅助合并：1",
        "明确分开：7",
        "候选对缓存命中：3",
        "输入 token：1200",
        "输出 token：240",
    ):
        assert expected in report
