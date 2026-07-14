from __future__ import annotations

from newsradar.sources.mixed_wave_reporting import render_mixed_wave_report
from newsradar.web.mixed_source_queries import (
    MixedSourceDashboard,
    MixedSourceGroup,
    MixedSourceSummary,
    MixedSourceTarget,
)


def _target(**overrides) -> MixedSourceTarget:
    values = {
        "source_id": "openai-youtube",
        "name": "OpenAI YouTube",
        "group": "youtube",
        "provider_id": "youtube",
        "coverage_mode": "direct",
        "availability": "requires_credentials",
        "state": "blocked",
        "state_label": "等待凭据或权限",
        "roles": ("discovery", "evidence"),
        "access_kind": "rest_api",
        "access_url": "https://www.googleapis.com/youtube/v3/channels",
        "recent_runs": (),
        "three_run_outcomes": (),
        "three_run_stable": False,
        "raw_item_count": 0,
        "latest_content_at": None,
        "latest_error_code": "missing_credentials",
        "conclusion_zh": "接口已登记，但当前缺少凭据。",
        "next_action_zh": "配置 YouTube API Key 后重新验证。",
    }
    values.update(overrides)
    return MixedSourceTarget(**values)


def test_report_explains_scope_runtime_evidence_and_next_action_in_chinese() -> None:
    dashboard = MixedSourceDashboard(
        summary=MixedSourceSummary(
            catalog_target_count=45,
            synced_target_count=45,
            direct_ready_count=16,
            indirect_ready_count=8,
            blocked_count=3,
            degraded_count=2,
            failed_count=1,
            not_run_count=15,
            three_run_stable_count=12,
        ),
        groups=(
            MixedSourceGroup(key="youtube", label="YouTube 视频", targets=(_target(),)),
        ),
    )

    report = render_mixed_wave_report(dashboard)

    assert "# News Codex 高价值混合来源健康报告" in report
    assert "目录目标 | 45" in report
    assert "直接抓取 | 16" in report
    assert "连续三轮稳定 | 12" in report
    assert "## YouTube 视频" in report
    assert "OpenAI YouTube" in report
    assert "等待凭据或权限" in report
    assert "尚未运行" in report
    assert "配置 YouTube API Key 后重新验证" in report


def test_report_never_exposes_credentials_or_query_secrets() -> None:
    target = _target(
        access_url="https://example.com/feed?key=secret-value&query=ai",
        next_action_zh="配置环境变量，不要记录真实密钥。",
    )
    dashboard = MixedSourceDashboard(
        summary=MixedSourceSummary(1, 1, 0, 0, 1, 0, 0, 0, 0),
        groups=(MixedSourceGroup("youtube", "YouTube 视频", (target,)),),
    )

    report = render_mixed_wave_report(dashboard)

    assert "secret-value" not in report
    assert "?key=" not in report
    assert "https://example.com/feed" in report
