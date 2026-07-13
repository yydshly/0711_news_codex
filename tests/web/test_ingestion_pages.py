from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from newsradar.db.models import (
    DuplicateCandidateRecord,
    FetchRunRecord,
    OperationRunRecord,
    RawItemRecord,
    RawItemSnapshotRecord,
)
from newsradar.settings import Settings
from newsradar.web.app import create_app


@contextmanager
def _session_context(session):
    yield session


def _client_with_database(monkeypatch, db_session):
    monkeypatch.setattr(
        "newsradar.web.app.create_session", lambda: _session_context(db_session)
    )
    return TestClient(create_app(), base_url="http://127.0.0.1")


def _action_token(page: str) -> str:
    return page.split('name="action_token" value="', 1)[1].split('"', 1)[0]


def test_pages_explain_system_network_inheritance_without_proxy_details(
    monkeypatch, db_session
):
    monkeypatch.setattr(
        "newsradar.web.app.get_settings",
        lambda: Settings(http_trust_env=True),
    )
    monkeypatch.setenv("HTTPS_PROXY", "http://user:secret@127.0.0.1:7890")
    with _client_with_database(monkeypatch, db_session) as client:
        page = client.get("/fetch-runs")

    assert page.status_code == 200
    assert "系统网络继承已启用" in page.text
    assert "来源探测与后台抓取将遵循本机网络环境" in page.text
    assert "127.0.0.1:7890" not in page.text
    assert "user:secret" not in page.text


def test_fetch_action_enqueues_once_and_never_fetches_in_request(monkeypatch, db_session):
    with _client_with_database(monkeypatch, db_session) as client:
        page = client.get("/operations")
        token = page.text.split('name="action_token" value="', 1)[1].split('"', 1)[0]
        response = client.post(
            "/operations/fetch",
            data={"source_id": "github-openai-python", "action_token": token},
            headers={"Origin": "http://127.0.0.1"},
            follow_redirects=False,
        )
        repeated = client.post(
            "/operations/fetch",
            data={"source_id": "github-openai-python", "action_token": token},
            headers={"Origin": "http://127.0.0.1"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/operations/")
    assert repeated.status_code == 400
    operations = db_session.scalars(select(OperationRunRecord)).all()
    assert len(operations) == 1
    assert operations[0].operation_type == "fetch"
    scope = dict(operations[0].requested_scope)
    assert datetime.fromisoformat(scope.pop("deadline_at")).tzinfo is not None
    assert scope == {
        "dry_run": False,
        "max_items": None,
        "one_off": False,
        "provider": None,
        "source_id": "github-openai-python",
    }
    assert operations[0].trigger == "web"


def test_fetch_action_rejects_non_loopback_origin_and_unknown_source(monkeypatch, db_session):
    with _client_with_database(monkeypatch, db_session) as client:
        page = client.get("/operations")
        token = page.text.split('name="action_token" value="', 1)[1].split('"', 1)[0]
        bad_origin = client.post(
            "/operations/fetch",
            data={"source_id": "github-openai-python", "action_token": token},
            headers={"Origin": "http://attacker.example"},
        )
        page = client.get("/operations")
        token = page.text.split('name="action_token" value="', 1)[1].split('"', 1)[0]
        unknown = client.post(
            "/operations/fetch",
            data={"source_id": "unknown", "action_token": token},
            headers={"Origin": "http://127.0.0.1"},
        )

    assert bad_origin.status_code == 400
    assert unknown.status_code == 422
    assert db_session.scalars(select(OperationRunRecord)).all() == []


def test_fetch_action_accepts_in_app_browser_opaque_same_origin(monkeypatch, db_session):
    with _client_with_database(monkeypatch, db_session) as client:
        page = client.get("/operations")
        token = _action_token(page.text)
        response = client.post(
            "/operations/fetch",
            data={"source_id": "github-openai-python", "action_token": token},
            headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"},
            follow_redirects=False,
        )

    assert response.status_code == 303


def test_ingestion_pages_project_runs_items_versions_and_duplicates(monkeypatch, db_session):
    run = FetchRunRecord(
        source_id="github-openai-python",
        started_at=datetime(2026, 7, 12, tzinfo=UTC),
        outcome="succeeded",
        item_count=2,
        items_received=5,
    )
    db_session.add(run)
    db_session.flush()
    first = RawItemRecord(
        source_id="github-openai-python",
        external_id="one",
        canonical_url="https://example.test/one",
        title="First record",
        payload={"token": "must-not-appear-in-list"},
        content_hash="one",
    )
    second = RawItemRecord(
        source_id="search-ai",
        external_id="two",
        canonical_url="https://example.test/two",
        title="Second record",
        payload={},
        content_hash="two",
    )
    db_session.add_all((first, second))
    db_session.flush()
    db_session.add(
        RawItemSnapshotRecord(
            raw_item_id=first.id,
            content_hash="one",
            snapshot={"title": "First record"},
        )
    )
    db_session.add(
        DuplicateCandidateRecord(
            raw_item_id=first.id,
            candidate_raw_item_id=second.id,
            match_type="canonical_url",
            score=1.0,
            status="pending",
        )
    )
    db_session.commit()

    with _client_with_database(monkeypatch, db_session) as client:
        runs = client.get("/fetch-runs")
        items = client.get("/items")
        detail = client.get(f"/items/{first.id}")
        duplicates = client.get("/duplicates")

    assert runs.status_code == items.status_code == detail.status_code == duplicates.status_code
    assert duplicates.status_code == 200
    assert "<td>5</td>" in runs.text
    assert "First record" in items.text
    assert "must-not-appear-in-list" not in items.text
    assert "https://example.test/one" in detail.text
    assert "canonical_url" in duplicates.text


def test_operation_actions_cancel_and_retry_with_independent_tokens(monkeypatch, db_session):
    queued = OperationRunRecord(
        operation_type="fetch",
        trigger="web",
        status="queued",
        requested_scope={"source_id": "github-openai-python"},
        result_summary={},
        attempt_count=0,
    )
    finished = OperationRunRecord(
        operation_type="fetch",
        trigger="web",
        status="succeeded",
        requested_scope={"source_id": "github-openai-python"},
        result_summary={},
        attempt_count=1,
    )
    db_session.add_all((queued, finished))
    db_session.commit()

    with _client_with_database(monkeypatch, db_session) as client:
        first_token = _action_token(client.get("/operations").text)
        second_token = _action_token(client.get("/operations").text)
        cancelled = client.post(
            f"/operations/{queued.id}/cancel",
            data={"action_token": first_token},
            headers={"Origin": "http://127.0.0.1"},
            follow_redirects=False,
        )
        retried = client.post(
            f"/operations/{finished.id}/retry",
            data={"action_token": second_token},
            headers={"Origin": "http://127.0.0.1"},
            follow_redirects=False,
        )
        retry_detail = client.get(retried.headers["location"])

    assert cancelled.status_code == 303
    assert retried.status_code == 303
    assert db_session.get(OperationRunRecord, queued.id).status == "cancelled"  # type: ignore[union-attr]
    retried_record = db_session.get(
        OperationRunRecord, int(retried.headers["location"].rsplit("/", 1)[1])
    )
    assert retried_record is not None
    assert retried_record.requested_scope["retry_of_operation_id"] == finished.id
    assert "由任务" in retry_detail.text
    assert f'href="/operations/{finished.id}"' in retry_detail.text
    assert f"#{finished.id}" in retry_detail.text
    assert "重试创建" in retry_detail.text


def test_duplicate_action_dismisses_pending_candidate(monkeypatch, db_session):
    first = RawItemRecord(
        source_id="github-openai-python",
        external_id="one",
        canonical_url="https://example.test/one",
        title="First record",
        payload={},
        content_hash="one",
    )
    second = RawItemRecord(
        source_id="search-ai",
        external_id="two",
        canonical_url="https://example.test/two",
        title="Second record",
        payload={},
        content_hash="two",
    )
    db_session.add_all((first, second))
    db_session.flush()
    candidate = DuplicateCandidateRecord(
        raw_item_id=first.id,
        candidate_raw_item_id=second.id,
        match_type="title",
        score=0.95,
        status="pending",
    )
    db_session.add(candidate)
    db_session.commit()

    with _client_with_database(monkeypatch, db_session) as client:
        token = _action_token(client.get("/operations").text)
        response = client.post(
            f"/duplicates/{candidate.id}/dismiss",
            data={"action_token": token},
            headers={"Origin": "http://127.0.0.1"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert db_session.get(DuplicateCandidateRecord, candidate.id).status == "dismissed"  # type: ignore[union-attr]


def test_operation_and_duplicate_pages_explain_available_safe_actions(monkeypatch, db_session):
    operation = OperationRunRecord(
        operation_type="fetch",
        trigger="web",
        status="queued",
        requested_scope={"source_id": "github-openai-python"},
        result_summary={},
        attempt_count=0,
    )
    db_session.add(operation)
    db_session.commit()

    with _client_with_database(monkeypatch, db_session) as client:
        detail = client.get(f"/operations/{operation.id}")
        duplicates = client.get("/duplicates")

    assert f"/operations/{operation.id}/cancel" in detail.text
    assert "重复候选需要人工裁决" in duplicates.text
