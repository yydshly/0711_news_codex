from __future__ import annotations

from contextlib import nullcontext

from fastapi.testclient import TestClient

from newsradar.web.app import create_app
from newsradar.web.mixed_source_queries import (
    MixedSourceDashboard,
    MixedSourceGroup,
    MixedSourceSummary,
    MixedSourceTarget,
)


def _dashboard() -> MixedSourceDashboard:
    target = MixedSourceTarget(
        source_id="openai-youtube",
        name="OpenAI YouTube",
        group="youtube",
        provider_id="youtube",
        coverage_mode="direct",
        availability="requires_credentials",
        state="blocked",
        state_label="等待凭据或权限",
        roles=("discovery", "evidence"),
        access_kind="rest_api",
        access_url="https://youtube.example/channels?key=secret-value",
        recent_runs=(),
        three_run_outcomes=(),
        three_run_stable=False,
        raw_item_count=18,
        latest_content_at=None,
        latest_error_code="missing_credentials",
        conclusion_zh="接口已登记，但尚未获得真实内容。",
        next_action_zh="配置本地环境变量后运行受控抓取。",
    )
    return MixedSourceDashboard(
        summary=MixedSourceSummary(45, 45, 16, 8, 3, 2, 1, 15, 12),
        groups=(MixedSourceGroup("youtube", "YouTube 视频", (target,)),),
    )


def test_mixed_sources_page_explains_scope_evidence_and_next_steps(monkeypatch) -> None:
    dashboard = _dashboard()
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: nullcontext(object()))
    monkeypatch.setattr(
        "newsradar.web.app.MixedSourceQueryService",
        lambda session: type("Service", (), {"build": lambda self: dashboard})(),
    )

    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        response = client.get("/mixed-sources")

    assert response.status_code == 200
    assert "高价值混合来源" in response.text
    assert "45" in response.text
    assert "直接抓取" in response.text
    assert "间接发现" in response.text
    assert "连续三轮稳定" in response.text
    assert "目录登记不等于已经抓取" in response.text
    assert "YouTube 视频" in response.text
    assert "OpenAI YouTube" in response.text
    assert "等待凭据或权限" in response.text
    assert "配置本地环境变量后运行受控抓取" in response.text
    assert 'href="/mixed-sources" aria-current="page"' in response.text
    assert 'href="/items?source_id=openai-youtube"' in response.text
    assert 'href="/fetch-runs?source_id=openai-youtube"' in response.text


def test_mixed_sources_page_does_not_expose_urls_or_credentials(monkeypatch) -> None:
    dashboard = _dashboard()
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: nullcontext(object()))
    monkeypatch.setattr(
        "newsradar.web.app.MixedSourceQueryService",
        lambda session: type("Service", (), {"build": lambda self: dashboard})(),
    )

    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        response = client.get("/mixed-sources")

    assert "secret-value" not in response.text
    assert "youtube.example" not in response.text
    assert "API_KEY=" not in response.text
