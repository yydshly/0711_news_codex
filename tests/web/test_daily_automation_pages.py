from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from newsradar.daily_reports.automation_repository import DailyAutomationRepository
from newsradar.daily_reports.autopilot import DailyAutopilotStage
from newsradar.daily_reports.autopilot_repository import DailyAutopilotRepository
from newsradar.db.models import OperationRunRecord, WorkerRecord
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.waves.planning import WaveMemberSnapshot, wave_plan_from_members
from newsradar.web.app import create_app
from newsradar.web.daily_automation_queries import DailyAutomationQueryService

NOW = datetime(2026, 7, 18, 1, 0, tzinfo=UTC)


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


def _client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    return TestClient(
        create_app(),
        base_url="http://127.0.0.1",
        headers={"Origin": "http://127.0.0.1"},
    )


def _action_token(client: TestClient) -> str:
    page = client.get("/daily-reports")
    assert page.status_code == 200
    return page.text.split('name="action_token" value="', 1)[1].split('"', 1)[0]


def test_fresh_daily_reports_page_shows_paused_automation_defaults(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(db_session, monkeypatch)

    response = client.get("/daily-reports")

    assert response.status_code == 200
    assert "日报自动化控制台" in response.text
    assert "已暂停" in response.text
    assert "每天 07:30" in response.text
    assert 'data-active-daily-run="true"' not in response.text
    assert DailyAutomationRepository(db_session).get_or_create().enabled is False


def test_enable_without_safe_action_is_forbidden(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.post("/daily-automation/enable")

    assert response.status_code == 403
    assert DailyAutomationRepository(db_session).get_or_create().enabled is False


def test_enable_rejects_cross_origin_even_with_valid_action_token(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(db_session, monkeypatch)
    token = _action_token(client)

    response = client.post(
        "/daily-automation/enable",
        data={"action_token": token},
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 403
    assert DailyAutomationRepository(db_session).get_or_create().enabled is False


def test_enable_then_pause_does_not_cancel_active_daily_run(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = DailyAutopilotRepository(db_session, utcnow=lambda: NOW)
    run = runs.create_run(window_hours=24, trigger="test", requested_scope={})
    runs.transition(run.id, stage=DailyAutopilotStage.WAIT_CONTENT_WAVE)
    run_id = run.id
    db_session.commit()
    client = _client(db_session, monkeypatch)

    enabled = client.post(
        "/daily-automation/enable",
        data={"action_token": _action_token(client)},
        follow_redirects=False,
    )
    paused = client.post(
        "/daily-automation/pause",
        data={"action_token": _action_token(client)},
        follow_redirects=False,
    )

    assert enabled.status_code == 303
    assert enabled.headers["location"] == "/daily-reports"
    assert paused.status_code == 303
    assert paused.headers["location"] == "/daily-reports"
    saved_run = DailyAutopilotRepository(db_session).get(run_id)
    assert saved_run.status == "running"
    assert saved_run.stage == DailyAutopilotStage.WAIT_CONTENT_WAVE.value
    assert DailyAutomationRepository(db_session).get_or_create().enabled is False


def test_run_now_uses_durable_autopilot_enqueue_and_redirects_to_detail(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "newsradar.web.app.build_local_wave_plan",
        lambda _session, *, window_hours: _wave_plan(window_hours),
    )
    client = _client(db_session, monkeypatch)

    response = client.post(
        "/daily-automation/run-now",
        data={"action_token": _action_token(client), "window_hours": "48"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/daily-autopilot/1"
    run = DailyAutopilotRepository(db_session).get(1)
    assert run.window_hours == 48
    assert run.trigger == "web"
    assert run.requested_scope["wave_plan"]["window_hours"] == 48


def test_run_now_rejects_unsupported_window(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(db_session, monkeypatch)

    response = client.post(
        "/daily-automation/run-now",
        data={"action_token": _action_token(client), "window_hours": "12"},
    )

    assert response.status_code == 422


def test_active_daily_run_renders_link_cancel_action_and_refresh_marker(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = DailyAutopilotRepository(db_session, utcnow=lambda: NOW).create_run(
        window_hours=24,
        trigger="schedule",
        requested_scope={},
    )
    run_id = run.id
    db_session.commit()
    client = _client(db_session, monkeypatch)

    response = client.get("/daily-reports")

    assert response.status_code == 200
    assert 'data-active-daily-run="true"' in response.text
    assert f'href="/daily-autopilot/{run_id}"' in response.text
    assert f'action="/daily-autopilot/{run_id}/cancel"' in response.text
    assert "准备真实内容抓取" in response.text


def test_worker_health_accepts_only_fresh_worker_or_running_operation_heartbeat(
    db_session: Session,
) -> None:
    threshold = NOW - timedelta(seconds=120)
    db_session.add(
        WorkerRecord(
            worker_id="stale",
            hostname="local",
            started_at=NOW - timedelta(hours=1),
            last_heartbeat_at=threshold,
            status="idle",
        )
    )
    db_session.add(
        OperationRunRecord(
            operation_type=OperationType.DAILY_AUTOPILOT.value,
            trigger="schedule",
            status=OperationStatus.RUNNING.value,
            requested_scope={},
            result_summary={},
            heartbeat_at=threshold + timedelta(microseconds=1),
        )
    )
    db_session.commit()

    online = DailyAutomationQueryService(
        db_session,
        utcnow=lambda: NOW,
        worker_lease_seconds=60,
    ).view()

    assert online.worker_online is True
    assert online.diagnostic == "调度服务在线"

    operation = db_session.query(OperationRunRecord).one()
    operation.heartbeat_at = threshold
    db_session.commit()
    offline = DailyAutomationQueryService(
        db_session,
        utcnow=lambda: NOW,
        worker_lease_seconds=60,
    ).view()

    assert offline.worker_online is False
    assert offline.diagnostic == "调度服务离线"

    worker = db_session.get(WorkerRecord, "stale")
    assert worker is not None
    worker.last_heartbeat_at = threshold + timedelta(seconds=1)
    db_session.commit()
    fresh_worker = DailyAutomationQueryService(
        db_session,
        utcnow=lambda: NOW,
        worker_lease_seconds=60,
    ).view()

    assert fresh_worker.worker_online is True


def test_automation_page_escapes_configuration_and_never_renders_secrets(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = DailyAutomationRepository(db_session, utcnow=lambda: NOW).get_or_create()
    config.timezone = 'Asia/Shanghai<script>alert("x")</script>'
    db_session.commit()
    client = _client(db_session, monkeypatch)

    response = client.get("/daily-reports")

    assert "<script>alert" not in response.text
    assert "&lt;script&gt;" in response.text
    assert "secret-token-value" not in response.text


def test_client_refresh_is_guarded_by_active_daily_run_marker() -> None:
    javascript = Path("src/newsradar/web/static/app.js").read_text(encoding="utf-8")

    assert '[data-active-daily-run="true"]' in javascript
    assert "10000" in javascript or "10_000" in javascript
    assert "location.reload" in javascript
