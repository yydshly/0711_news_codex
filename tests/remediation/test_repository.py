from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    FetchRunRecord,
    OperationRunRecord,
    SourceAccessMethodRecord,
    SourceAcquisitionCandidateRecord,
    SourceAcquisitionProbeRunRecord,
    SourceDefinitionRecord,
    SourceProbeRunRecord,
    SourceProbeSampleRecord,
    SourceRemediationBatchRecord,
)
from newsradar.sources.repository import SourceRepository
from newsradar.sources.schema import SourceDefinition
from tests.test_source_schema import valid_source


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def source(
    session: Session,
    source_id: str,
    name: str,
    *,
    coverage_mode: str = "direct",
    auth_envs: list[str] | None = None,
) -> None:
    session.add(
        SourceDefinitionRecord(
            id=source_id,
            name=name,
            provider_id="independent",
            target_type="publisher_feed",
            availability="ready",
            coverage_mode=coverage_mode,
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
        SourceAccessMethodRecord(
            source_id=source_id,
            kind="rss",
            url="https://example.test/feed",
            priority=1,
            requires_manual_approval=False,
            auth_envs=auth_envs or [],
            headers={},
            params={},
        )
    )


def probe(source_id: str, finished_at: datetime, outcome: str, *, status: int | None = None):
    return SourceProbeRunRecord(
        source_id=source_id,
        access_kind="rss",
        access_url="https://example.test/feed",
        outcome=outcome,
        started_at=finished_at - timedelta(seconds=1),
        finished_at=finished_at,
        http_status=status,
        suggested_status="degraded",
        reason="fixture",
        error_code=f"http_{status}" if status else None,
        metrics={},
    )


def test_manifest_keeps_latest_failure_at_or_before_baseline_after_later_success():
    from newsradar.remediation.repository import RemediationRepository

    baseline = datetime(2026, 7, 13, 10, tzinfo=UTC)
    with make_session() as session:
        source(session, "alpha", "Alpha")
        session.add(probe("alpha", baseline - timedelta(minutes=1), "failed", status=404))
        session.add(probe("alpha", baseline + timedelta(minutes=1), "success", status=200))
        session.commit()

        manifest = RemediationRepository(session).manifest(baseline)

    assert manifest.baseline_at == baseline
    assert len(manifest.entries) == 1
    assert manifest.entries[0].source_id == "alpha"
    assert manifest.entries[0].category.value == "endpoint_changed"


def test_manifest_excludes_source_whose_latest_baseline_probe_succeeded():
    from newsradar.remediation.repository import RemediationRepository

    baseline = datetime(2026, 7, 13, 10, tzinfo=UTC)
    with make_session() as session:
        source(session, "alpha", "Alpha")
        session.add(probe("alpha", baseline - timedelta(minutes=2), "failed", status=503))
        session.add(probe("alpha", baseline - timedelta(minutes=1), "success", status=200))
        session.commit()

        manifest = RemediationRepository(session).manifest(baseline)

    assert manifest.entries == ()


def test_manifest_excludes_expected_non_trial_sources_before_failure_classification():
    from newsradar.remediation.repository import RemediationRepository

    baseline = datetime(2026, 7, 13, 10, tzinfo=UTC)
    with make_session() as session:
        source(session, "catalog", "Catalog", coverage_mode="catalog_only")
        source(session, "credentialed", "Credentialed", auth_envs=["API_TOKEN"])
        session.add(probe("catalog", baseline, "blocked", status=403))
        session.add(probe("credentialed", baseline, "blocked", status=401))
        session.commit()

        manifest = RemediationRepository(session).manifest(baseline)

    assert manifest.entries == ()


def test_enriched_manifest_combines_candidate_probe_trial_and_fetch_evidence():
    from newsradar.remediation.repository import RemediationRepository

    baseline = datetime(2026, 7, 13, 10, tzinfo=UTC)
    data = valid_source()
    data["id"] = "alpha"
    data["name"] = "Alpha"
    data["research"] = {
        "status": "needs_research",
        "candidates": [
            {
                "key": "official-feed",
                "kind": "rss",
                "implementation": "feedparser",
                "officiality": "official",
                "authentication": "none",
                "roles": ["discovery"],
                "fields": ["title", "canonical_url"],
                "limitations": [],
                "evidence": ["https://example.test/feed"],
                "reviewed_at": "2026-07-13",
                "sample_status": "succeeded",
                "decision": "primary",
            }
        ],
    }
    definition = SourceDefinition.model_validate(data)
    with make_session() as session:
        SourceRepository(session).sync([definition])
        session.add(probe("alpha", baseline, "failed"))
        successful = probe("alpha", baseline + timedelta(hours=1), "success")
        successful.metrics = {"sample_count": 5, "field_completeness": 1.0}
        session.add(successful)
        session.flush()
        session.add(
            SourceProbeSampleRecord(
                probe_run_id=successful.id,
                sample_index=0,
                canonical_url="https://example.test/item",
                published_at=baseline,
                fields_present=["title", "canonical_url"],
                sample_hash="sample-hash",
            )
        )
        candidate = session.scalar(
            select(SourceAcquisitionCandidateRecord).where(
                SourceAcquisitionCandidateRecord.source_id == "alpha"
            )
        )
        remediation_operation = OperationRunRecord(
            operation_type="source_remediation",
            trigger="cli",
            status="succeeded",
            requested_scope={
                "source_id": "alpha",
                "candidate_key": "official-feed",
                "original_probe_id": 1,
                "baseline_at": baseline.isoformat(),
            },
            result_summary={},
        )
        session.add(remediation_operation)
        session.flush()
        acquisition = SourceAcquisitionProbeRunRecord(
            candidate_id=candidate.id,
            operation_run_id=remediation_operation.id,
            original_probe_id=1,
            started_at=baseline,
            completed_at=baseline + timedelta(minutes=1),
            outcome="succeeded",
            http_status=200,
            fields_present=["title", "canonical_url"],
            sample_count=5,
            details={},
        )
        session.add(acquisition)
        session.flush()
        successful.remediation_acquisition_probe_id = acquisition.id
        operation = OperationRunRecord(
            operation_type="fetch",
            trigger="cli",
            status="succeeded",
            requested_scope={
                "source_id": "alpha",
                "trial": True,
                "remediation_content_probe_id": successful.id,
            },
            result_summary={},
        )
        session.add(operation)
        session.flush()
        session.add(
            FetchRunRecord(
                source_id="alpha",
                outcome="succeeded",
                item_count=5,
                operation_run_id=operation.id,
                items_received=5,
                items_inserted=5,
            )
        )
        session.commit()

        repository = RemediationRepository(session)
        repository.freeze_manifest(baseline, [definition], before_trial_count=16)
        manifest = repository.enriched_manifest(baseline, [definition])
        rejected_manifests = []
        for operation_type, status, scope in (
            ("fetch", "failed", operation.requested_scope),
            ("fetch", "cancelled", operation.requested_scope),
            ("fetch", "interrupted", operation.requested_scope),
            ("event_pipeline", "succeeded", operation.requested_scope),
            (
                "fetch",
                "succeeded",
                {**operation.requested_scope, "source_id": "another-source"},
            ),
        ):
            operation.operation_type = operation_type
            operation.status = status
            operation.requested_scope = dict(scope)
            session.commit()
            rejected_manifests.append(repository.enriched_manifest(baseline, [definition]))
        operation.operation_type = "fetch"
        operation.status = "succeeded"
        operation.requested_scope = {
            "source_id": "alpha",
            "trial": True,
            "remediation_content_probe_id": successful.id,
        }
        session.commit()

    assert manifest.before_trial_count == 16
    assert manifest.after_trial_count == 1
    evidence = manifest.entries[0].evidence
    assert evidence.candidate_key == "official-feed"
    assert evidence.acquisition_outcome == "succeeded"
    assert evidence.content_outcome == "success"
    assert evidence.trial_eligible is True
    assert evidence.fetch_outcome == "succeeded"
    assert evidence.fetch_items_inserted == 5
    assert all(
        item.entries[0].evidence.fetch_outcome is None for item in rejected_manifests
    )


def test_enriched_manifest_rejects_unfrozen_batch_without_writing() -> None:
    from newsradar.remediation.repository import RemediationRepository

    baseline = datetime(2026, 7, 13, 10, tzinfo=UTC)
    with make_session() as session:
        source(session, "alpha", "Alpha")
        session.add(probe("alpha", baseline, "failed", status=404))
        session.commit()

        with pytest.raises(ValueError, match="remediation_batch_not_frozen"):
            RemediationRepository(session).enriched_manifest(baseline, [])

        assert session.scalar(select(SourceRemediationBatchRecord)) is None


def test_frozen_manifest_does_not_change_after_live_definition_changes() -> None:
    from newsradar.remediation.repository import RemediationRepository

    baseline = datetime(2026, 7, 13, 10, tzinfo=UTC)
    with make_session() as session:
        source(session, "alpha", "Alpha")
        session.add(probe("alpha", baseline, "failed", status=404))
        session.commit()
        repository = RemediationRepository(session)

        frozen = repository.freeze_manifest(baseline, before_trial_count=16)
        record = session.get(SourceDefinitionRecord, "alpha")
        record.name = "Renamed"
        record.coverage_mode = "catalog_only"
        record.definition_hash = "changed"
        session.commit()

        same_batch = repository.manifest(baseline)

    assert frozen == same_batch
    assert same_batch.entries[0].source_name == "Alpha"
    assert same_batch.entries[0].category.value == "endpoint_changed"
