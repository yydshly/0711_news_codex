from datetime import UTC

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from newsradar.ai.minimax import ModelUsage
from newsradar.db.models import (
    Base,
    FetchRunRecord,
    ModelUsageRecord,
    SourceAccessMethodRecord,
    SourceDefinitionRecord,
    SourceDefinitionVersion,
    SourceProbeRunRecord,
    SourceProbeSampleRecord,
)
from newsradar.sources.probes.base import ProbeOutcome, ProbeResult, ProbeSample
from newsradar.sources.repository import SourceRepository
from newsradar.sources.schema import SourceDefinition

from .test_source_schema import valid_source


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_sync_creates_current_definition_and_immutable_version() -> None:
    source = SourceDefinition.model_validate(valid_source())
    with make_session() as session:
        result = SourceRepository(session).sync([source])
        session.commit()

        assert result.created == 1
        assert session.scalar(select(func.count()).select_from(SourceDefinitionRecord)) == 1
        assert session.scalar(select(func.count()).select_from(SourceDefinitionVersion)) == 1


def test_sync_is_idempotent_for_unchanged_yaml() -> None:
    source = SourceDefinition.model_validate(valid_source())
    with make_session() as session:
        repository = SourceRepository(session)
        repository.sync([source])
        first = repository.sync([source])
        session.commit()

        assert first.unchanged == 1
        assert session.scalar(select(func.count()).select_from(SourceDefinitionVersion)) == 1


def test_sync_versions_changed_definition_without_auto_activation() -> None:
    original = SourceDefinition.model_validate(valid_source())
    changed_data = valid_source()
    changed_data["poll_interval_minutes"] = 120
    changed_data["status"] = "active"
    changed = SourceDefinition.model_validate(changed_data)

    with make_session() as session:
        repository = SourceRepository(session)
        repository.sync([original])
        result = repository.sync([changed])
        session.commit()

        current = session.get(SourceDefinitionRecord, original.id)
        assert result.updated == 1
        assert current is not None
        assert current.poll_interval_minutes == 120
        assert current.status == "candidate"
        assert session.scalar(select(func.count()).select_from(SourceDefinitionVersion)) == 2


def test_sync_preserves_access_method_referenced_by_fetch_history() -> None:
    original = SourceDefinition.model_validate(valid_source())
    changed_data = valid_source()
    changed_data["poll_interval_minutes"] = 120
    changed = SourceDefinition.model_validate(changed_data)

    with make_session() as session:
        session.execute(text("PRAGMA foreign_keys=ON"))
        repository = SourceRepository(session)
        repository.sync([original])
        session.flush()
        access_method = session.scalar(select(SourceAccessMethodRecord))
        assert access_method is not None
        session.add(
            FetchRunRecord(
                source_id=original.id,
                access_method_id=access_method.id,
                outcome="success",
            )
        )
        session.commit()

        repository.sync([changed])
        session.commit()

        preserved = session.scalar(select(SourceAccessMethodRecord))
        fetch_run = session.scalar(select(FetchRunRecord))
        assert preserved is not None
        assert fetch_run is not None
        assert preserved.id == access_method.id
        assert fetch_run.access_method_id == preserved.id


def test_save_probe_result_persists_metrics_without_secrets() -> None:
    from datetime import datetime

    source = SourceDefinition.model_validate(valid_source())
    now = datetime.now(UTC)
    result = ProbeResult(
        source_id=source.id,
        access_kind="rss",
        access_url="https://www.anthropic.com/news/rss.xml",
        outcome=ProbeOutcome.SUCCESS,
        started_at=now,
        finished_at=now,
        http_status=200,
        response_headers={"etag": '"v1"'},
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
    with make_session() as session:
        repository = SourceRepository(session)
        repository.sync([source])
        repository.save_probe_result(result)
        session.commit()
        assert session.scalar(select(func.count()).select_from(SourceProbeRunRecord)) == 1
        assert session.scalar(select(func.count()).select_from(SourceProbeSampleRecord)) == 1


def test_save_model_usage_persists_only_operational_metadata() -> None:
    usage = ModelUsage(
        purpose="infer_source_topics",
        model="MiniMax-M2.7-highspeed",
        input_tokens=100,
        output_tokens=20,
        latency_ms=45.0,
        outcome="success",
    )
    with make_session() as session:
        SourceRepository(session).save_model_usage(usage)
        session.commit()
        record = session.scalar(select(ModelUsageRecord))
        assert record is not None
        assert record.purpose == "infer_source_topics"
        assert not hasattr(record, "prompt")
