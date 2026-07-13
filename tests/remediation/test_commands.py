from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import Base, OperationRunRecord
from newsradar.operations.commands import OperationCommandService


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_enqueue_source_remediation_captures_immutable_probe_scope() -> None:
    with make_session() as session:
        operation_id = OperationCommandService(session).enqueue_source_remediation(
            source_id="alpha",
            candidate_key="official-rss",
            original_probe_id=17,
            baseline_at=datetime(2026, 7, 13, tzinfo=UTC),
            trigger="cli",
        )
        operation = session.get(OperationRunRecord, operation_id)

    assert operation is not None
    assert operation.operation_type == "source_remediation"
    assert operation.requested_scope["original_probe_id"] == 17
    assert operation.requested_scope["source_id"] == "alpha"


def test_enqueue_source_remediation_rejects_another_active_remediation() -> None:
    with make_session() as session:
        commands = OperationCommandService(session)
        commands.enqueue_source_remediation(
            source_id="alpha",
            candidate_key="official-rss",
            original_probe_id=17,
            baseline_at=datetime(2026, 7, 13, tzinfo=UTC),
            trigger="cli",
        )

        with pytest.raises(ValueError, match="active_source_remediation_exists"):
            commands.enqueue_source_remediation(
                source_id="beta",
                candidate_key="official-api",
                original_probe_id=18,
                baseline_at=datetime(2026, 7, 13, tzinfo=UTC),
                trigger="cli",
            )


def test_generic_retry_rejects_source_remediation_operation() -> None:
    with make_session() as session:
        commands = OperationCommandService(session)
        operation_id = commands.enqueue_source_remediation(
            source_id="alpha",
            candidate_key="official-rss",
            original_probe_id=17,
            baseline_at=datetime(2026, 7, 13, tzinfo=UTC),
            trigger="cli",
        )
        operation = session.get(OperationRunRecord, operation_id)
        assert operation is not None
        operation.status = "failed"
        session.commit()

        with pytest.raises(ValueError, match="operation is not retryable"):
            commands.retry(operation_id, trigger="cli")
