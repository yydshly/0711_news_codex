from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import Base
from newsradar.ingestion.trial import (
    ProbeSnapshot,
    TrialDecision,
    evaluate_trial_eligibility,
)
from newsradar.sources.probes.base import ProbeOutcome, ProbeResult, ProbeSample
from newsradar.sources.repository import SourceRepository
from newsradar.sources.schema import SourceDefinition
from tests.test_source_schema import valid_source


def _source(**changes: object) -> SourceDefinition:
    data = valid_source()
    data.update(changes)
    return SourceDefinition.model_validate(data)


def _successful_probe(**changes: object) -> ProbeSnapshot:
    values: dict[str, object] = {
        "outcome": "success",
        "sample_count": 1,
        "field_completeness": 1.0,
        "sample_fields": frozenset({"title", "canonical_url"}),
        "finished_at": datetime(2026, 7, 13, tzinfo=UTC),
    }
    values.update(changes)
    return ProbeSnapshot(**values)


def test_direct_ready_successful_probe_is_trial_eligible() -> None:
    decision = evaluate_trial_eligibility(_source(), _successful_probe())

    assert decision.eligible is True
    assert decision.code is None
    assert decision.reason == "可试用抓取：公开直连且首次探测合格"


def test_indirect_source_is_discovery_only() -> None:
    decision = evaluate_trial_eligibility(
        _source(coverage_mode="indirect"), _successful_probe()
    )

    assert decision == TrialDecision(False, "discovery_only", "仅用于发现，需回源确认")


def test_catalog_only_source_has_a_distinct_reason() -> None:
    decision = evaluate_trial_eligibility(
        _source(coverage_mode="catalog_only"), _successful_probe()
    )

    assert decision.code == "catalog_only"


@pytest.mark.parametrize(
    "probe",
    [
        _successful_probe(sample_fields=frozenset({"title"})),
        _successful_probe(field_completeness=0.59),
    ],
)
def test_probe_without_required_fields_or_completeness_is_not_eligible(
    probe: ProbeSnapshot,
) -> None:
    decision = evaluate_trial_eligibility(_source(), probe)

    assert decision.eligible is False


def test_repository_reads_the_latest_probe_snapshot() -> None:
    source = _source()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repository = SourceRepository(session)
        repository.sync([source])
        assert repository.latest_probe_snapshot(source.id) is None

        finished_at = datetime(2026, 7, 13, tzinfo=UTC)
        repository.save_probe_result(
            ProbeResult(
                source_id=source.id,
                access_kind="rss",
                access_url="https://www.anthropic.com/news/rss.xml",
                outcome=ProbeOutcome.SUCCESS,
                started_at=finished_at,
                finished_at=finished_at,
                sample_count=1,
                field_completeness=1.0,
                samples=[
                    ProbeSample(
                        external_id="1",
                        title="Release",
                        canonical_url="https://www.anthropic.com/news/release",
                    )
                ],
                suggested_status="candidate",
                reason="ok",
            )
        )

        snapshot = repository.latest_probe_snapshot(source.id)
        assert snapshot is not None
        assert snapshot.outcome == "success"
        assert snapshot.sample_count == 1
        assert snapshot.field_completeness == 1.0
        assert snapshot.sample_fields == frozenset({"title", "canonical_url"})
        assert snapshot.finished_at == finished_at.replace(tzinfo=None)
