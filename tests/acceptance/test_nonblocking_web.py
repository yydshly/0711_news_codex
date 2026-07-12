from __future__ import annotations

from contextlib import contextmanager
from threading import Event, Thread

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from newsradar.db.models import Base, SourceDefinitionRecord
from newsradar.operations.repository import OperationRepository
from newsradar.operations.worker import Worker
from newsradar.web.app import create_app


@contextmanager
def _session_context(session: Session):
    yield session


def test_web_enqueue_and_read_routes_return_while_worker_is_busy(monkeypatch) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(
        SourceDefinitionRecord(
            id="github-openai-python",
            name="OpenAI Python",
            status="active",
            nature="first_party",
            language="en",
            roles=["discovery"],
            topics=["ai"],
            authority_score=5,
            poll_interval_minutes=60,
            expected_fields=["title"],
            definition_hash="github-openai-python-hash",
        )
    )
    db.commit()
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: _session_context(db))
    started, release = Event(), Event()

    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        page = client.get("/operations")
        token = page.text.split('name="action_token" value="', 1)[1].split('"', 1)[0]
        response = client.post(
            "/operations/fetch",
            data={"source_id": "github-openai-python", "action_token": token},
            headers={"Origin": "http://127.0.0.1"},
            follow_redirects=False,
        )
        operation_id = int(response.headers["location"].rstrip("/").split("/")[-1])

        def run_slow_worker() -> None:
            Worker(OperationRepository(db), "worker-slow").run_once(
                lambda lease, checkpoint: (
                    started.set(),
                    release.wait(timeout=2),
                    checkpoint("source"),
                )
            )

        thread = Thread(target=run_slow_worker)
        thread.start()
        assert started.wait(timeout=1)
        detail = client.get(f"/operations/{operation_id}")
        listing = client.get("/operations")
        release.set()
        thread.join(timeout=2)

    assert response.status_code == 303
    assert detail.status_code == listing.status_code == 200
    assert not thread.is_alive()
