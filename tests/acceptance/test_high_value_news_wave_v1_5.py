"""PostgreSQL acceptance checks for the v1.5 wave without external source I/O."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, current_thread
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, delete, select
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from newsradar.db.models import (
    HighValueWaveMemberRecord,
    OperationAttemptRecord,
    OperationRunRecord,
    SourceDefinitionRecord,
    WorkerRecord,
)
from newsradar.operations.repository import OperationLease, OperationRepository
from newsradar.settings import Settings
from newsradar.sources.yaml_loader import load_source_tree
from newsradar.waves.loader import load_wave_profile
from newsradar.waves.planning import build_wave_plan
from newsradar.waves.repository import WaveRepository


def _postgres_engine_or_skip():
    if os.getenv("NEWSRADAR_RUN_POSTGRES_ACCEPTANCE") != "1":
        pytest.skip("set NEWSRADAR_RUN_POSTGRES_ACCEPTANCE=1 to run real PostgreSQL acceptance")
    database_url = Settings().database_url
    if not database_url or not database_url.startswith("postgresql"):
        pytest.skip("project-local PostgreSQL DATABASE_URL is not configured")
    engine = create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            if connection.dialect.name != "postgresql":
                pytest.skip("configured database is not PostgreSQL")
    except SQLAlchemyError as error:
        engine.dispose()
        pytest.skip(f"project-local PostgreSQL is unavailable: {error.__class__.__name__}")
    return engine


def test_postgres_schema_is_at_current_project_head_for_high_value_wave() -> None:
    """Never silently perform the acceptance run against a stale database schema."""
    engine = _postgres_engine_or_skip()
    try:
        config = Config("alembic.ini")
        expected = ScriptDirectory.from_config(config).get_current_head()
        with engine.connect() as connection:
            actual = MigrationContext.configure(connection).get_current_revision()
        assert actual == expected
    finally:
        engine.dispose()


def test_high_value_profile_freezes_all_35_targets_before_any_network_request() -> None:
    """The profile remains a 35-target, side-effect-free input to every real round."""
    profile = load_wave_profile(Path("wave_profiles/high-value-ai-tech.yaml"))
    plan = build_wave_plan(profile, load_source_tree(Path("sources")), {}, set())

    assert len(plan.members) == 35
    assert {member.source_id for member in plan.members} == set(profile.source_ids)
    assert all(member.fetchable is False for member in plan.members)
    assert all(member.blocked_reason is not None for member in plan.members)


def test_postgres_wave_member_finish_does_not_deadlock_with_lease_renewal() -> None:
    """Exercise the real FK lock order that previously deadlocked production waves."""
    engine = _postgres_engine_or_skip()
    suffix = uuid4().hex
    worker_id = f"wave-lock-order-{suffix}"
    operation_id: int | None = None
    attempt_id: int | None = None
    operation_locked = Event()
    member_update_started = Event()
    release_renewal = Event()
    try:
        with Session(engine) as setup:
            source_id = setup.scalar(select(SourceDefinitionRecord.id).limit(1))
            assert source_id is not None, "source catalog must be synced before acceptance"
            now = datetime.now(UTC)
            setup.add(
                WorkerRecord(
                    worker_id=worker_id,
                    hostname=worker_id,
                    started_at=now,
                    last_heartbeat_at=now,
                    status="running",
                )
            )
            setup.flush()
            operation = OperationRunRecord(
                operation_type="high_value_news_wave",
                trigger="acceptance",
                status="running",
                requested_scope={},
                result_summary={},
                worker_id=worker_id,
                attempt_count=1,
                progress_total=1,
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=60),
            )
            setup.add(operation)
            setup.flush()
            operation_id = operation.id
            attempt = OperationAttemptRecord(
                operation_run_id=operation.id,
                worker_id=worker_id,
                attempt_number=1,
                status="running",
                claimed_at=now,
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=60),
            )
            setup.add(attempt)
            setup.flush()
            attempt_id = attempt.id
            setup.add(
                HighValueWaveMemberRecord(
                    operation_run_id=operation.id,
                    source_id=source_id,
                    provider_id="acceptance",
                    definition_hash=suffix,
                    nature_snapshot="community",
                    roles_snapshot=["discovery"],
                    availability_snapshot="ready",
                    access_kind_snapshot="rss",
                    fetchable=True,
                    state="running",
                    claim_attempt_id=attempt.id,
                )
            )
            setup.commit()

        @sqlalchemy_event.listens_for(engine, "after_cursor_execute")
        def pause_after_operation_lock(_conn, _cursor, statement, _params, _context, _many):
            normalized = statement.lower()
            if (
                current_thread().name == "lease-renewal"
                and "from operation_runs" in normalized
                and "for update" in normalized
            ):
                operation_locked.set()
                assert release_renewal.wait(timeout=5), "renewal lock was not released"

        @sqlalchemy_event.listens_for(engine, "before_cursor_execute")
        def observe_member_update(_conn, _cursor, statement, _params, _context, _many):
            if (
                current_thread().name == "member-finish"
                and statement.lower().startswith("update high_value_wave_members")
            ):
                member_update_started.set()

        assert operation_id is not None and attempt_id is not None
        lease = OperationLease(
            operation_id,
            attempt_id,
            1,
            worker_id,
            {},
            "high_value_news_wave",
        )

        def renew() -> bool:
            with Session(engine) as session:
                return OperationRepository(session).renew_lease(lease, lease_seconds=60)

        def finish() -> str:
            with Session(engine) as session:
                record = WaveRepository(session).finish_member(
                    operation_id,
                    source_id,
                    state="succeeded",
                    result_code=None,
                    conclusion="done",
                    claim_attempt_id=attempt_id,
                )
                session.commit()
                return record.state

        def named_renew() -> bool:
            current_thread().name = "lease-renewal"
            return renew()

        def named_finish() -> str:
            current_thread().name = "member-finish"
            return finish()

        with ThreadPoolExecutor(max_workers=2) as pool:
            renewal = pool.submit(named_renew)
            assert operation_locked.wait(timeout=5), "renewal did not lock the operation"
            member = pool.submit(named_finish)
            assert member_update_started.wait(timeout=5), "member did not start its update"
            # Let PostgreSQL reach the FK lock wait before allowing renewal to continue.
            time.sleep(0.2)
            release_renewal.set()
            assert renewal.result(timeout=10) is True
            assert member.result(timeout=10) == "succeeded"
    finally:
        release_renewal.set()
        if "pause_after_operation_lock" in locals():
            sqlalchemy_event.remove(
                engine, "after_cursor_execute", pause_after_operation_lock
            )
        if "observe_member_update" in locals():
            sqlalchemy_event.remove(
                engine, "before_cursor_execute", observe_member_update
            )
        if operation_id is not None:
            with Session(engine) as cleanup:
                cleanup.execute(
                    delete(HighValueWaveMemberRecord).where(
                        HighValueWaveMemberRecord.operation_run_id == operation_id
                    )
                )
                cleanup.execute(
                    delete(OperationAttemptRecord).where(
                        OperationAttemptRecord.operation_run_id == operation_id
                    )
                )
                cleanup.execute(
                    delete(OperationRunRecord).where(OperationRunRecord.id == operation_id)
                )
                cleanup.execute(delete(WorkerRecord).where(WorkerRecord.worker_id == worker_id))
                cleanup.commit()
        engine.dispose()
