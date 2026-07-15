from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import Base, SourceDefinitionRecord
from newsradar.sources.catalog_reconcile import (
    CatalogReconcileBlocked,
    apply_reconcile_plan,
    build_reconcile_plan,
)
from newsradar.sources.repository import SourceRepository
from newsradar.sources.schema import SourceDefinition

from .test_source_schema import valid_source


@pytest.fixture
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def yaml_source(source_id: str) -> SourceDefinition:
    payload = valid_source()
    payload["id"] = source_id
    payload["name"] = source_id
    return SourceDefinition.model_validate(payload)


def seed_source(db_session, source_id: str) -> SourceDefinitionRecord:
    SourceRepository(db_session).sync([yaml_source(source_id)])
    db_session.commit()
    return db_session.get(SourceDefinitionRecord, source_id)


def test_reconcile_archives_only_missing_yaml_sources(db_session) -> None:
    seed_source(db_session, "keep")
    seed_source(db_session, "legacy")

    plan = build_reconcile_plan(db_session, {"keep"})

    assert plan.archive_ids == ("legacy",)
    apply_reconcile_plan(db_session, plan)
    assert db_session.get(SourceDefinitionRecord, "legacy").catalog_state == "archived"
    assert db_session.get(SourceDefinitionRecord, "keep").catalog_state == "current"


def test_sync_restores_archived_source(db_session) -> None:
    record = seed_source(db_session, "alpha")
    record.catalog_state = "archived"
    record.catalog_archived_at = datetime.now(UTC)
    record.catalog_archive_reason = "absent_from_current_yaml"
    db_session.commit()

    SourceRepository(db_session).sync([yaml_source("alpha")])

    assert record.catalog_state == "current"
    assert record.catalog_archived_at is None


def test_apply_reconcile_refuses_active_operation(db_session) -> None:
    from newsradar.operations.repository import OperationRepository
    from newsradar.operations.schema import OperationType

    seed_source(db_session, "legacy")
    OperationRepository(db_session).enqueue(OperationType.FETCH, {"source_id": "legacy"})
    db_session.commit()

    plan = build_reconcile_plan(db_session, set())

    with pytest.raises(CatalogReconcileBlocked):
        apply_reconcile_plan(db_session, plan)
    assert db_session.get(SourceDefinitionRecord, "legacy").catalog_state == "current"
