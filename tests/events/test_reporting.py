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
        window_hours=72,
        selected_count=12,
        processed_count=12,
        included_count=5,
        excluded_count=7,
        exclusion_reasons=(("generic_technology", 4), ("insufficient_text", 3)),
        candidate_count=3,
        visibility_counts=(("current", 2), ("legacy", 72)),
        status_counts=(("confirmed", 1), ("emerging", 1)),
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
        "# Event Intelligence v2 事件质量验收报告",
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
