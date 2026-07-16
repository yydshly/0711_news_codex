from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from newsradar.waves.reporting import render_high_value_wave_report


def test_report_contains_evidence_sections_and_no_secrets() -> None:
    operation = SimpleNamespace(
        id=41,
        status="partial",
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
        finished_at=datetime(2026, 7, 16, 1, tzinfo=UTC),
        requested_scope={"profile_id": "high-value-ai-tech", "window_hours": 24, "trend_days": 7},
        result_summary={
            "completed_members": 2,
            "member_total": 2,
            "model_degraded": True,
            "evidence_capable_members": 1,
            "direct_evidence_fetch_succeeded": 1,
            "events_with_official_root": 1,
            "events_with_one_professional_root": 1,
            "events_with_two_professional_roots": 1,
            "confirmed_event_count": 2,
            "ambiguous_pairs_checked": 3,
            "model_pair_fallback_count": 1,
        },
    )
    members = [
        SimpleNamespace(
            source_id="hn",
            provider_id="hacker-news",
            fetchable=True,
            state="succeeded",
            result_code=None,
            conclusion="ok",
        ),
        SimpleNamespace(
            source_id="youtube",
            provider_id="youtube",
            fetchable=False,
            state="blocked",
            result_code="missing_credentials",
            conclusion="Authorization: Bearer secret Cookie=session-secret",
        ),
    ]
    events = [
        {
            "title": "已证实发布",
            "signal_state": "confirmed",
            "heat": 87,
            "trend": "rising",
            "evidence_roots": 2,
        },
        {
            "title": "社区讨论",
            "signal_state": "early_signal",
            "heat": 44,
            "trend": "sustained",
            "evidence_roots": 0,
        },
    ]

    report = render_high_value_wave_report(operation, members, events)

    assert "已确认热点" in report
    assert "早期信号" in report
    assert "7 天趋势" in report
    assert "已证实发布" in report
    assert "社区讨论" in report
    assert "Authorization" not in report
    assert "Cookie" not in report
    assert "session-secret" not in report
    for expected in (
        "证据型成员",
        "直接证据抓取成功",
        "含官方证据根事件",
        "含一个专业媒体根事件",
        "含两个专业媒体根事件",
        "已确认事件",
        "边界候选检查",
        "模型配对保守回退",
    ):
        assert expected in report
