from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from newsradar.db.models import OperationRunRecord, WorkerRecord
from newsradar.web.routes.system import build_system_health


def test_system_health_reports_stale_worker_queue_and_error_category(db_session) -> None:
    now = datetime.now(UTC)
    db_session.add_all(
        [
            WorkerRecord(
                worker_id="stale-worker",
                hostname="local",
                started_at=now - timedelta(hours=2),
                last_heartbeat_at=now - timedelta(minutes=10),
                status="online",
            ),
            OperationRunRecord(
                operation_type="fetch",
                trigger="manual",
                status="queued",
                requested_scope={},
                result_summary={},
            ),
            OperationRunRecord(
                operation_type="fetch",
                trigger="manual",
                status="failed",
                requested_scope={},
                result_summary={},
                error_code="quota_exhausted",
            ),
        ]
    )
    db_session.commit()

    health = build_system_health(db_session, now=now)

    assert health.database_status == "online"
    assert health.queue_depth == 1
    assert health.worker_status == "stale"
    assert health.error_categories == (("quota_exhausted", 1),)


def test_system_page_is_read_only_and_renders_health(monkeypatch, db_session) -> None:
    from newsradar.web import create_app

    monkeypatch.setattr("newsradar.web.app.create_session", lambda: nullcontext(db_session))

    response = TestClient(create_app()).get("/system")

    assert response.status_code == 200
    assert "系统健康" in response.text


def test_system_page_shows_credential_names_and_configuration_only(
    monkeypatch, db_session
) -> None:
    from newsradar.web import create_app

    class Credentials:
        def configured_names(self) -> set[str]:
            return {"GITHUB_TOKEN", "YOUTUBE_API_KEY"}

    monkeypatch.setattr("newsradar.web.app.create_session", lambda: nullcontext(db_session))
    monkeypatch.setattr("newsradar.web.app.SettingsCredentials", Credentials)

    response = TestClient(create_app()).get("/system")

    assert "GITHUB_TOKEN：已配置" in response.text
    assert "REDDIT_CLIENT_SECRET：未配置" in response.text
    assert "YOUTUBE_API_KEY：已配置" in response.text
    assert "secret-value" not in response.text


def test_system_diagnostic_post_rejects_non_loopback_host(monkeypatch, db_session) -> None:
    from newsradar.web import create_app

    monkeypatch.setattr("newsradar.web.app.create_session", lambda: nullcontext(db_session))

    response = TestClient(create_app()).post(
        "/system/diagnostics", headers={"host": "example.com", "origin": "http://example.com"}
    )

    assert response.status_code == 400
