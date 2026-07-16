"""PostgreSQL acceptance checks for the v1.5 wave without external source I/O."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from newsradar.settings import Settings
from newsradar.sources.yaml_loader import load_source_tree
from newsradar.waves.loader import load_wave_profile
from newsradar.waves.planning import build_wave_plan


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
