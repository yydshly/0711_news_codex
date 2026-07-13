from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    OperationRunRecord,
    SourceAcquisitionCandidateRecord,
    SourceAcquisitionProbeRunRecord,
    SourceDefinitionRecord,
    SourceProbeRunRecord,
    SourceRemediationBatchRecord,
    SourceRemediationMemberRecord,
)
from newsradar.operations.commands import OperationCommandService


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def register_batch(session: Session, *members: tuple[str, int]) -> datetime:
    baseline = datetime(2026, 7, 13, tzinfo=UTC)
    batch = SourceRemediationBatchRecord(baseline_at=baseline)
    session.add(batch)
    session.flush()
    for source_id, probe_id in members:
        session.add(
            SourceDefinitionRecord(
                id=source_id,
                name=source_id,
                provider_id="independent",
                status="candidate",
                nature="first_party",
                language="en",
                roles=["discovery"],
                topics=["ai"],
                authority_score=5,
                poll_interval_minutes=60,
                expected_fields=["title", "canonical_url"],
                definition_hash=f"hash-{source_id}",
            )
        )
        session.add(
            SourceProbeRunRecord(
                id=probe_id,
                source_id=source_id,
                access_kind="rss",
                access_url="https://example.test/feed",
                outcome="failed",
                started_at=baseline,
                finished_at=baseline,
                response_headers={},
                metrics={},
                suggested_status="degraded",
                reason="fixture",
            )
        )
        session.flush()
        session.add(
            SourceRemediationMemberRecord(
                batch_id=batch.id,
                source_id=source_id,
                source_name=source_id,
                provider_id="independent",
                definition_hash=f"hash-{source_id}",
                original_probe_id=probe_id,
                original_finished_at=baseline,
                category="network_transient",
                reason_zh="测试",
                next_action_zh="复查",
            )
        )
    session.commit()
    return baseline


def register_content_evidence(session: Session, source_id: str, original_probe_id: int) -> int:
    candidate = SourceAcquisitionCandidateRecord(
        source_id=source_id,
        candidate_key="official-rss",
        kind="rss",
        implementation="feedparser",
        officiality="official",
        authentication="none",
        roles=["discovery"],
        fields=["title", "canonical_url"],
        limitations=[],
        evidence=["https://example.test/feed"],
        sample_status="succeeded",
        decision="primary",
        reviewed_at=datetime(2026, 7, 13, tzinfo=UTC).date(),
    )
    session.add(candidate)
    remediation = OperationRunRecord(
        operation_type="source_remediation",
        trigger="cli",
        status="succeeded",
        requested_scope={
            "source_id": source_id,
            "candidate_key": candidate.candidate_key,
            "original_probe_id": original_probe_id,
        },
        result_summary={},
    )
    session.add(remediation)
    session.flush()
    acquisition = SourceAcquisitionProbeRunRecord(
        candidate_id=candidate.id,
        operation_run_id=remediation.id,
        original_probe_id=original_probe_id,
        started_at=datetime(2026, 7, 13, tzinfo=UTC),
        completed_at=datetime(2026, 7, 13, tzinfo=UTC),
        outcome="succeeded",
        details={},
    )
    session.add(acquisition)
    session.flush()
    content = SourceProbeRunRecord(
        source_id=source_id,
        remediation_acquisition_probe_id=acquisition.id,
        access_kind="rss",
        access_url="https://example.test/feed",
        outcome="success",
        started_at=datetime(2026, 7, 13, tzinfo=UTC),
        finished_at=datetime(2026, 7, 13, tzinfo=UTC),
        response_headers={},
        metrics={"sample_count": 1, "field_completeness": 1.0},
        suggested_status="candidate",
        reason="ok",
    )
    session.add(content)
    session.commit()
    return content.id


def test_enqueue_source_remediation_captures_immutable_probe_scope() -> None:
    with make_session() as session:
        baseline = register_batch(session, ("alpha", 17))
        operation_id = OperationCommandService(session).enqueue_source_remediation(
            source_id="alpha",
            candidate_key="official-rss",
            original_probe_id=17,
            baseline_at=baseline,
            trigger="cli",
        )
        operation = session.get(OperationRunRecord, operation_id)

    assert operation is not None
    assert operation.operation_type == "source_remediation"
    assert operation.requested_scope["original_probe_id"] == 17
    assert operation.requested_scope["source_id"] == "alpha"


def test_enqueue_source_remediation_rejects_source_outside_frozen_batch() -> None:
    with make_session() as session:
        baseline = register_batch(session, ("alpha", 17))

        with pytest.raises(ValueError, match="source_not_in_frozen_remediation_batch"):
            OperationCommandService(session).enqueue_source_remediation(
                source_id="alpha",
                candidate_key="official-rss",
                original_probe_id=18,
                baseline_at=baseline,
                trigger="cli",
            )


def test_enqueue_source_remediation_rejects_another_active_remediation() -> None:
    with make_session() as session:
        baseline = register_batch(session, ("alpha", 17), ("beta", 18))
        commands = OperationCommandService(session)
        commands.enqueue_source_remediation(
            source_id="alpha",
            candidate_key="official-rss",
            original_probe_id=17,
            baseline_at=baseline,
            trigger="cli",
        )

        with pytest.raises(ValueError, match="active_source_remediation_exists"):
            commands.enqueue_source_remediation(
                source_id="beta",
                candidate_key="official-api",
                original_probe_id=18,
                baseline_at=baseline,
                trigger="cli",
            )


def test_generic_retry_rejects_source_remediation_operation() -> None:
    with make_session() as session:
        baseline = register_batch(session, ("alpha", 17))
        commands = OperationCommandService(session)
        operation_id = commands.enqueue_source_remediation(
            source_id="alpha",
            candidate_key="official-rss",
            original_probe_id=17,
            baseline_at=baseline,
            trigger="cli",
        )
        operation = session.get(OperationRunRecord, operation_id)
        assert operation is not None
        operation.status = "failed"
        session.commit()

        with pytest.raises(ValueError, match="operation is not retryable"):
            commands.retry(operation_id, trigger="cli")


def test_source_remediation_allows_one_explicit_retry_for_network_transient() -> None:
    with make_session() as session:
        baseline = register_batch(session, ("alpha", 17))
        commands = OperationCommandService(session)
        operation_id = commands.enqueue_source_remediation(
            source_id="alpha",
            candidate_key="official-rss",
            original_probe_id=17,
            baseline_at=baseline,
            trigger="cli",
        )
        operation = session.get(OperationRunRecord, operation_id)
        assert operation is not None
        operation.status = "failed"
        operation.result_summary = {"category": "network_transient"}
        session.commit()

        retry_id = commands.retry_source_remediation(operation_id, trigger="cli")
        retry = session.get(OperationRunRecord, retry_id)

        assert retry is not None
        assert retry.requested_scope["retry_of_operation_id"] == operation_id
        with pytest.raises(ValueError, match="source_remediation_retry_not_allowed"):
            commands.retry_source_remediation(operation_id, trigger="cli")


def test_enqueue_fetch_accepts_only_strongly_linked_trial_content_probe() -> None:
    with make_session() as session:
        register_batch(session, ("alpha", 17))
        content_probe_id = register_content_evidence(session, "alpha", 17)

        operation_id = OperationCommandService(session).enqueue_fetch(
            source_id="alpha",
            trial=True,
            remediation_content_probe_id=content_probe_id,
            trigger="cli",
        )
        operation = session.get(OperationRunRecord, operation_id)

    assert operation is not None
    assert operation.requested_scope["remediation_content_probe_id"] == content_probe_id


def test_enqueue_fetch_rejects_unlinked_or_non_trial_remediation_evidence() -> None:
    with make_session() as session:
        register_batch(session, ("alpha", 17))
        content_probe_id = register_content_evidence(session, "alpha", 17)
        commands = OperationCommandService(session)

        with pytest.raises(ValueError, match="remediation_content_link_requires_trial"):
            commands.enqueue_fetch(
                source_id="alpha",
                trial=False,
                remediation_content_probe_id=content_probe_id,
                trigger="cli",
            )
        with pytest.raises(ValueError, match="invalid_remediation_content_link"):
            commands.enqueue_fetch(
                source_id="other",
                trial=True,
                remediation_content_probe_id=content_probe_id,
                trigger="cli",
            )
