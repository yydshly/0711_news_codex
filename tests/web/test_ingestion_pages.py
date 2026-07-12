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
from newsradar.web.app import create_app


@contextmanager
def _session_context(session):
    yield session


def _client_with_database(monkeypatch, db_session):
    monkeypatch.setattr(
        "newsradar.web.app.create_session", lambda: _session_context(db_session)
    )
    return TestClient(create_app(), base_url="http://127.0.0.1")


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
    assert operations[0].requested_scope == {
        "dry_run": False,
        "provider": None,
        "source_id": "github-openai-python",
    }


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


def test_ingestion_pages_project_runs_items_versions_and_duplicates(monkeypatch, db_session):
    run = FetchRunRecord(
        source_id="github-openai-python",
        started_at=datetime(2026, 7, 12, tzinfo=UTC),
        outcome="succeeded",
        item_count=2,
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
    assert "First record" in items.text
    assert "must-not-appear-in-list" not in items.text
    assert "https://example.test/one" in detail.text
    assert "canonical_url" in duplicates.text
