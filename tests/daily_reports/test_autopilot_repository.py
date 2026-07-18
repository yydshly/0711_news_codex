from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.daily_reports.autopilot import DailyAutopilotStage
from newsradar.daily_reports.autopilot_repository import DailyAutopilotRepository
from newsradar.db.models import Base

NOW = datetime(2026, 7, 18, 1, tzinfo=UTC)


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_autopilot_run_persists_stage_scope_and_linked_operation(
    db_session: Session,
) -> None:
    repository = DailyAutopilotRepository(db_session, utcnow=lambda: NOW)

    run = repository.create_run(
        window_hours=24,
        trigger="web",
        requested_scope={"wave_plan": {"members": []}},
    )
    assert run.stage == DailyAutopilotStage.ENQUEUE_CONTENT_WAVE.value
    saved = repository.transition(
        run.id,
        stage=DailyAutopilotStage.WAIT_SOURCE_REFRESH,
        source_operation_id=41,
    )

    assert saved.status == "running"
    assert saved.stage == DailyAutopilotStage.WAIT_SOURCE_REFRESH.value
    assert saved.source_operation_id == 41
    assert saved.requested_scope == {"wave_plan": {"members": []}}


def test_autopilot_repository_rejects_second_active_run(db_session: Session) -> None:
    repository = DailyAutopilotRepository(db_session, utcnow=lambda: NOW)
    repository.create_run(window_hours=24, trigger="web", requested_scope={})

    with pytest.raises(ValueError, match="active_daily_autopilot_exists"):
        repository.create_run(window_hours=24, trigger="web", requested_scope={})
