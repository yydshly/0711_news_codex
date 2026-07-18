from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from newsradar.daily_reports.autopilot import DailyAutopilotStage, serialize_catalog_plan
from newsradar.daily_reports.autopilot_repository import DailyAutopilotRepository
from newsradar.db.models import OperationRunRecord
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.sources.catalog_refresh import (
    CatalogRefreshLane,
    CatalogRefreshMemberSnapshot,
    CatalogRefreshPlan,
)
from newsradar.waves.planning import WaveMemberSnapshot, wave_plan_from_members
from newsradar.web.app import create_app


def _plan() -> CatalogRefreshPlan:
    return CatalogRefreshPlan.from_members(
        [
            CatalogRefreshMemberSnapshot(
                source_id="source-a",
                provider_id="provider-a",
                definition_hash="source-hash",
                availability="ready",
                coverage_mode="direct",
                access_kind="rss",
                lane=CatalogRefreshLane.CONTENT,
            )
        ]
    )


def _wave_plan(window_hours: int):
    return wave_plan_from_members(
        profile_id="high-value",
        members=(
            WaveMemberSnapshot(
                "source-a",
                "provider-a",
                "source-hash",
                ("evidence",),
                "ready",
                "rss",
                True,
                None,
            ),
        ),
        window_hours=window_hours,
        trend_days=7,
    )


def _client_with_token(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, str]:
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    client = TestClient(
        create_app(),
        base_url="http://127.0.0.1",
        headers={"Origin": "http://127.0.0.1"},
    )
    page = client.get("/operations")
    token = page.text.split('name="action_token" value="', 1)[1].split('"', 1)[0]
    return client, token


def test_autopilot_post_queues_then_redirects_to_task_page(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "newsradar.web.app._high_value_wave_plan",
        lambda _session, window_hours=None: _wave_plan(window_hours or 24),
    )
    client, token = _client_with_token(db_session, monkeypatch)

    response = client.post(
        "/daily-reports/autopilot",
        data={"action_token": token, "window_hours": "72"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/daily-autopilot/1"
    run = DailyAutopilotRepository(db_session).get(1)
    assert run.window_hours == 72
    assert run.stage == DailyAutopilotStage.ENQUEUE_CONTENT_WAVE.value
    assert run.requested_scope["wave_plan"]["window_hours"] == 72
    assert "catalog_plan" not in run.requested_scope


def test_task_page_shows_child_links_and_chinese_partial_reason(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = OperationRunRecord(
        operation_type=OperationType.SOURCE_CATALOG_REFRESH.value,
        trigger="test",
        status=OperationStatus.PARTIAL.value,
        requested_scope={},
        result_summary={},
    )
    db_session.add(source)
    db_session.flush()
    run = DailyAutopilotRepository(db_session).create_run(
        window_hours=24,
        trigger="web",
        requested_scope={"catalog_plan": serialize_catalog_plan(_plan())},
    )
    DailyAutopilotRepository(db_session).transition(
        run.id,
        stage=DailyAutopilotStage.WAIT_SOURCE_REFRESH,
        source_operation_id=source.id,
    )
    run_id = run.id
    db_session.commit()
    client, _token = _client_with_token(db_session, monkeypatch)

    response = client.get(f"/daily-autopilot/{run_id}")

    assert response.status_code == 200
    assert "来源刷新" in response.text
    assert f'href="/operations/{source.id}"' in response.text
    assert "部分来源未成功" in response.text
