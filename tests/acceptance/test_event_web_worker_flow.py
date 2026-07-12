from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from newsradar.db.models import Base, OperationRunRecord, RawItemRecord, SourceDefinitionRecord
from newsradar.events.runtime import EventOperationHandler
from newsradar.operations.repository import OperationRepository
from newsradar.operations.router import OperationRouter
from newsradar.operations.worker import Worker
from newsradar.web.app import create_app


def test_web_enqueue_worker_publish_and_event_detail(monkeypatch) -> None:
    """A web build request remains durable until the worker publishes its detail page."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(
        SourceDefinitionRecord(
            id="acceptance-official",
            name="Acceptance official source",
            status="active",
            nature="first_party",
            language="en",
            roles=["evidence"],
            topics=["ai"],
            authority_score=90,
            poll_interval_minutes=60,
            expected_fields=[],
            definition_hash="acceptance-official",
        )
    )
    session.add(
        RawItemRecord(
            source_id="acceptance-official",
            external_id="event-1",
            canonical_url="https://example.test/events/1",
            payload={},
            title="OpenAI launches an AI model",
            published_at=datetime.now(UTC),
        )
    )
    session.commit()
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: session)
    monkeypatch.setattr("newsradar.web.app.consume_one_time_token", lambda *_: None)

    with TestClient(create_app()) as client:
        response = client.post(
            "/events/build",
            data={"action_token": "acceptance-token", "window_hours": "24"},
            headers={"Origin": "http://127.0.0.1", "Host": "127.0.0.1"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        operation_id = int(response.headers["location"].rsplit("/", 1)[1])

        router = OperationRouter(
            {"event_pipeline": EventOperationHandler.production(lambda: Session(engine))}
        )
        assert Worker(OperationRepository(session), "acceptance-event-worker").run_once(router)
        operation = session.get(OperationRunRecord, operation_id)
        assert operation is not None
        assert operation.status in {"succeeded", "partial"}
        event_id = operation.result_summary["event_ids"][0]
        detail = client.get(f"/events/{event_id}")

    assert detail.status_code == 200
    assert "https://example.test/events/1" in detail.text
    session.close()
    engine.dispose()
