from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    ProviderDefinitionRecord,
    ProviderDefinitionVersion,
    ProviderProbeRunRecord,
)
from newsradar.providers.probes import ProviderProbeResult
from newsradar.providers.repository import ProviderRepository
from newsradar.providers.schema import ProviderDefinition

from .test_provider_schema import valid_provider


def session_for_test() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def provider(**updates) -> ProviderDefinition:
    data = valid_provider()
    data.update(updates)
    return ProviderDefinition.model_validate(data)


def test_provider_sync_is_idempotent_and_versions_changes() -> None:
    with session_for_test() as session:
        repository = ProviderRepository(session)

        created = repository.sync([provider()])
        unchanged = repository.sync([provider()])
        updated = repository.sync([provider(notes="Public AppView")])
        session.commit()

        assert (created.created, created.updated, created.unchanged) == (1, 0, 0)
        assert (unchanged.created, unchanged.updated, unchanged.unchanged) == (0, 0, 1)
        assert (updated.created, updated.updated, updated.unchanged) == (0, 1, 0)
        record = session.get(ProviderDefinitionRecord, "bluesky")
        assert record is not None
        assert record.notes == "Public AppView"
        versions = session.scalars(select(ProviderDefinitionVersion)).all()
        assert len(versions) == 2
        assert versions[0].definition != versions[1].definition


def test_provider_probe_history_contains_capability_not_content() -> None:
    with session_for_test() as session:
        repository = ProviderRepository(session)
        repository.sync([provider()])
        checked_at = datetime.now(UTC)

        record = repository.save_probe(
            provider_id="bluesky",
            outcome="success",
            availability="ready",
            reason="Official public endpoint is reachable",
            checked_at=checked_at,
            latency_ms=12.5,
            http_status=200,
            evidence_url="https://docs.bsky.app/",
        )
        session.commit()

        stored = session.get(ProviderProbeRunRecord, record.id)
        assert stored is not None
        assert stored.probe_type == "capability"
        assert stored.provider_id == "bluesky"
        assert not hasattr(stored, "samples")


def test_provider_probe_result_can_be_persisted_without_shape_conversion() -> None:
    with session_for_test() as session:
        repository = ProviderRepository(session)
        repository.sync([provider()])
        result = ProviderProbeResult(
            provider_id="bluesky",
            outcome="success",
            availability="ready",
            reason="reachable",
            checked_at=datetime.now(UTC),
            evidence_url="https://docs.bsky.app/",
        )

        record = repository.save_probe(**result.model_dump())

        assert record.probe_type == "capability"


def test_latest_probes_returns_newest_record_per_provider() -> None:
    with session_for_test() as session:
        repository = ProviderRepository(session)
        repository.sync([provider()])
        older = datetime(2026, 7, 10, tzinfo=UTC)
        newer = datetime(2026, 7, 11, tzinfo=UTC)
        for checked_at, outcome in ((older, "failed"), (newer, "success")):
            repository.save_probe(
                provider_id="bluesky",
                outcome=outcome,
                availability="ready",
                reason=outcome,
                checked_at=checked_at,
                latency_ms=1,
                http_status=200,
                evidence_url="https://docs.bsky.app/",
            )
        session.commit()

        latest = repository.latest_probes()

        assert latest["bluesky"].outcome == "success"
        assert latest["bluesky"].checked_at.replace(tzinfo=UTC) == newer
