from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import select

from newsradar.db.models import OperationRunRecord, SourceCatalogRefreshMemberRecord
from newsradar.sources.catalog_refresh import (
    CatalogRefreshLane,
    CatalogRefreshMemberSnapshot,
    CatalogRefreshPlan,
)
from newsradar.web.app import create_app


@contextmanager
def _session_context(session):
    yield session


def _client(monkeypatch, session) -> TestClient:
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: _session_context(session))
    return TestClient(create_app(), base_url="http://127.0.0.1")


def _token(page: str) -> str:
    return page.split('name="action_token" value="', 1)[1].split('"', 1)[0]


def test_source_waves_page_is_read_only_and_shows_chinese_navigation(
    monkeypatch, db_session
) -> None:
    with _client(monkeypatch, db_session) as client:
        response = client.get("/source-waves")

    assert response.status_code == 200
    assert "全量盘点" in response.text
    assert "网页只创建队列任务" in response.text


def test_source_wave_post_enqueues_and_redirects_without_network(monkeypatch, db_session) -> None:
    monkeypatch.setattr(
        "newsradar.web.app._source_wave_plan",
        lambda: CatalogRefreshPlan.from_members(
            (
                CatalogRefreshMemberSnapshot(
                    source_id="github-openai-python",
                    provider_id="github",
                    definition_hash="a" * 64,
                    availability="ready",
                    coverage_mode="direct",
                    access_kind="rss",
                    lane=CatalogRefreshLane.CONTENT,
                ),
            )
        ),
    )
    with _client(monkeypatch, db_session) as client:
        page = client.get("/source-waves")
        response = client.post(
            "/source-waves",
            data={"action_token": _token(page.text)},
            headers={"origin": "http://127.0.0.1"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    operation = db_session.scalar(select(OperationRunRecord))
    assert operation is not None
    assert operation.operation_type == "source_catalog_refresh"
    assert response.headers["location"] == f"/source-waves/{operation.id}"


def test_source_wave_writes_reuse_safe_action_boundary(monkeypatch, db_session) -> None:
    with _client(monkeypatch, db_session) as client:
        missing_token = client.post("/source-waves", headers={"origin": "http://127.0.0.1"})
        remote = client.post(
            "/source-waves",
            headers={"host": "example.com", "origin": "http://example.com"},
        )

    assert missing_token.status_code == 400
    assert remote.status_code == 400


def test_active_wave_disables_create_and_detail_uses_chinese_outcome_labels(
    monkeypatch, db_session
) -> None:
    active = OperationRunRecord(
        operation_type="source_catalog_refresh",
        trigger="test",
        status="queued",
        requested_scope={},
        result_summary={},
    )
    db_session.add(active)
    db_session.commit()
    with _client(monkeypatch, db_session) as client:
        page = client.get("/source-waves")
        detail = client.get(f"/source-waves/{active.id}")

    assert "disabled" in page.text
    assert "已有活动批次" in page.text
    assert detail.status_code == 200
    assert "内容成功" in detail.text
    assert "能力已确认" in detail.text
    assert "目录已确认" in detail.text
    assert "运行失败" in detail.text


def test_source_wave_cancel_and_retry_reuse_safe_action_boundary(monkeypatch, db_session) -> None:
    queued = OperationRunRecord(
        operation_type="source_catalog_refresh",
        trigger="test",
        status="queued",
        requested_scope={},
        result_summary={},
    )
    failed = OperationRunRecord(
        operation_type="source_catalog_refresh",
        trigger="test",
        status="failed",
        requested_scope={},
        result_summary={},
    )
    db_session.add_all((queued, failed))
    db_session.flush()
    db_session.add(
        SourceCatalogRefreshMemberRecord(
            operation_run_id=failed.id,
            source_id="github-openai-python",
            provider_id="github",
            definition_hash="a" * 64,
            availability_snapshot="ready",
            coverage_mode_snapshot="direct",
            access_kind_snapshot="rss",
            lane="content",
            state="failed",
            result_code="timeout",
            conclusion="超时",
            content_probe_run_ids=[],
            attempt_count=1,
        )
    )
    db_session.commit()
    with _client(monkeypatch, db_session) as client:
        cancel_token = _token(client.get(f"/source-waves/{queued.id}").text)
        cancelled = client.post(
            f"/source-waves/{queued.id}/cancel",
            data={"action_token": cancel_token},
            headers={"origin": "http://127.0.0.1"},
            follow_redirects=False,
        )
        retry_token = _token(client.get(f"/source-waves/{failed.id}").text)
        retried = client.post(
            f"/source-waves/{failed.id}/retry",
            data={"action_token": retry_token},
            headers={"origin": "http://127.0.0.1"},
            follow_redirects=False,
        )

    assert cancelled.status_code == 303
    assert db_session.get(OperationRunRecord, queued.id).cancel_requested_at is not None
    assert retried.status_code == 303
    assert retried.headers["location"] != f"/source-waves/{failed.id}"


def test_source_wave_cancel_rejects_other_operation_type_without_mutation(
    monkeypatch, db_session
) -> None:
    other = OperationRunRecord(
        operation_type="fetch",
        trigger="test",
        status="queued",
        requested_scope={},
        result_summary={},
    )
    db_session.add(other)
    db_session.commit()
    with _client(monkeypatch, db_session) as client:
        token = _token(client.get("/source-waves").text)
        response = client.post(
            f"/source-waves/{other.id}/cancel",
            data={"action_token": token},
            headers={"origin": "http://127.0.0.1"},
        )

    assert response.status_code == 404
    assert db_session.get(OperationRunRecord, other.id).cancel_requested_at is None


def test_source_wave_abandoned_recovery_requires_confirmation_and_safe_action(
    monkeypatch, db_session
) -> None:
    wave = OperationRunRecord(
        operation_type="source_catalog_refresh",
        trigger="test",
        status="partial",
        requested_scope={},
        result_summary={},
    )
    db_session.add(wave)
    db_session.flush()
    db_session.add(
        SourceCatalogRefreshMemberRecord(
            operation_run_id=wave.id,
            source_id="github-openai-python",
            provider_id="github",
            definition_hash="a" * 64,
            availability_snapshot="ready",
            coverage_mode_snapshot="direct",
            access_kind_snapshot="rss",
            lane="content",
            state="running",
            content_probe_run_ids=[],
            attempt_count=1,
        )
    )
    db_session.commit()
    with _client(monkeypatch, db_session) as client:
        token = _token(client.get(f"/source-waves/{wave.id}").text)
        rejected = client.post(
            f"/source-waves/{wave.id}/recover-abandoned",
            data={"action_token": token},
            headers={"origin": "http://127.0.0.1"},
            follow_redirects=False,
        )
        token = _token(client.get(f"/source-waves/{wave.id}").text)
        recovered = client.post(
            f"/source-waves/{wave.id}/recover-abandoned",
            data={"action_token": token, "confirm_abandoned": "true"},
            headers={"origin": "http://127.0.0.1"},
            follow_redirects=False,
        )

    assert rejected.status_code == 409
    assert recovered.status_code == 303
