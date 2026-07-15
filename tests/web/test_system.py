from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from newsradar.db.models import OperationRunRecord, WorkerRecord
from newsradar.settings import Settings
from newsradar.web.routes.system import build_minimax_runtime_view, build_system_health


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


def test_system_health_distinguishes_idle_busy_and_stale(db_session) -> None:
    now = datetime.now(UTC)
    db_session.add_all(
        [
            WorkerRecord(
                worker_id="idle", hostname="local", started_at=now,
                last_heartbeat_at=now, status="idle"
            ),
            WorkerRecord(
                worker_id="busy", hostname="local", started_at=now,
                last_heartbeat_at=now, status="running", current_operation_run_id=1
            ),
            WorkerRecord(
                worker_id="stale", hostname="local", started_at=now,
                last_heartbeat_at=now - timedelta(minutes=10), status="idle"
            ),
        ]
    )
    db_session.commit()

    health = build_system_health(db_session, now=now)

    assert health.idle_worker_count == 1
    assert health.busy_worker_count == 1
    assert health.stale_worker_count == 1
    assert health.online_worker_count == 2


def test_minimax_runtime_view_is_safe_and_uses_config_only(db_session) -> None:
    view = build_minimax_runtime_view(
        db_session,
        Settings(
            _env_file=None,
            minimax_api_key="secret-value",
            minimax_base_url="https://api.minimaxi.com",
        ),
    )

    assert view.configured is True
    assert view.region == "china"
    assert "secret-value" not in repr(view)


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


def test_system_page_shows_minimax_summary_without_secrets(monkeypatch, db_session) -> None:
    from newsradar.web import create_app

    monkeypatch.setattr("newsradar.web.app.create_session", lambda: nullcontext(db_session))
    monkeypatch.setattr(
        "newsradar.web.app.get_settings",
        lambda: Settings(
            _env_file=None,
            minimax_api_key="secret-value",
            minimax_base_url="https://api.minimaxi.com",
        ),
    )

    response = TestClient(create_app()).get("/system")

    assert "MiniMax 运行状态" in response.text
    assert "中国区" in response.text
    assert "MiniMax-M2.7-highspeed" in response.text
    assert "newsradar serve --host 127.0.0.1 --port 8766" in response.text
    assert "secret-value" not in response.text
    assert "api.minimaxi.com" not in response.text


def test_system_diagnostic_post_rejects_non_loopback_host(monkeypatch, db_session) -> None:
    from newsradar.web import create_app

    monkeypatch.setattr("newsradar.web.app.create_session", lambda: nullcontext(db_session))

    response = TestClient(create_app()).post(
        "/system/diagnostics", headers={"host": "example.com", "origin": "http://example.com"}
    )

    assert response.status_code == 400
