from datetime import UTC, datetime

from fastapi.testclient import TestClient

from newsradar.db.models import (
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    OperationRunRecord,
)
from newsradar.web.app import create_app


def _add_event(session, event_id=41, status="confirmed", title="确认事件"):
    session.add(
        EventRecord(
            id=event_id,
            canonical_key=f"e-{event_id}",
            status=status,
            occurred_at=datetime.now(UTC),
            current_version_number=1,
        )
    )
    session.add(
        EventVersionRecord(
            event_id=event_id, version_number=1, zh_title=title, zh_summary="已核验摘要", payload={}
        )
    )
    session.add(
        EventScoreRecord(
            event_id=event_id, version_number=1, heat=88, breakdown={"reasons": ["官方来源"]}
        )
    )
    session.commit()


def test_home_shows_confirmed_events_and_not_social_only(db_session, monkeypatch):
    _add_event(db_session)
    _add_event(db_session, 42, "emerging", "社交线索")
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    with TestClient(create_app()) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "确认事件" in response.text
    assert "社交线索" not in response.text


def test_emerging_page_labels_unconfirmed_social_signal(db_session, monkeypatch):
    _add_event(db_session, 42, "emerging", "社交线索")
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    with TestClient(create_app()) as client:
        response = client.get("/emerging")
    assert response.status_code == 200
    assert "仅线索" in response.text
    assert "社交线索" in response.text


def test_recluster_post_only_enqueues_operation(db_session, monkeypatch):
    _add_event(db_session)
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    with TestClient(create_app()) as client:
        token = (
            client.get("/events/41").text.split('name="action_token" value="')[1].split('"', 1)[0]
        )
        response = client.post(
            "/events/41/recluster",
            data={"action_token": token},
            headers={"Origin": "http://127.0.0.1", "Host": "127.0.0.1"},
            follow_redirects=False,
        )
    assert response.status_code == 303
    operation = db_session.query(OperationRunRecord).one()
    assert operation.operation_type == "event_recluster"
    assert operation.trigger == "web"
    assert operation.requested_scope["actor"] == "web"


def test_event_detail_does_not_render_unsafe_evidence_href(db_session, monkeypatch):
    from newsradar.db.models import EventItemRecord, RawItemRecord

    _add_event(db_session)
    raw = RawItemRecord(
        source_id="github-openai-python",
        external_id="unsafe-link",
        canonical_url="javascript:alert(1)",
        payload={},
        title="不安全链接",
    )
    db_session.add(raw)
    db_session.flush()
    db_session.add(EventItemRecord(event_id=41, raw_item_id=raw.id, added_version_number=1))
    db_session.commit()
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        response = client.get("/events/41")

    assert response.status_code == 200
    assert 'href="javascript:' not in response.text
