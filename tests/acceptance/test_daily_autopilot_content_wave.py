from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from newsradar.daily_reports.autopilot import DailyAutopilotStage
from newsradar.daily_reports.autopilot_repository import DailyAutopilotRepository
from newsradar.daily_reports.autopilot_runtime import DailyAutopilotHandler
from newsradar.daily_reports.repository import DailyReportRepository
from newsradar.db.models import (
    Base,
    DailyReportRecord,
    FetchRunRecord,
    HighValueWaveMemberRecord,
    OperationRunRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.ingestion.schema import FetchOutcome, FetchResult
from newsradar.ingestion.service import SourceFetchSummary
from newsradar.operations.commands import OperationCommandService
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.settings import Settings
from newsradar.sources.repository import canonical_definition
from newsradar.sources.schema import SourceDefinition
from newsradar.waves.planning import (
    WaveMemberSnapshot,
    wave_plan_from_members,
)
from newsradar.waves.runtime import HighValueWaveHandler


def _source(source_id: str) -> SourceDefinition:
    return SourceDefinition.model_validate(
        {
            "id": source_id,
            "name": source_id,
            "status": "active",
            "nature": "first_party",
            "roles": ["discovery", "evidence"],
            "language": "en",
            "topics": ["ai"],
            "authority_score": 5,
            "poll_interval_minutes": 60,
            "official_identity_url": f"https://{source_id}.test",
            "access_methods": [
                {
                    "kind": "rss",
                    "url": f"https://{source_id}.test/feed",
                    "priority": 1,
                }
            ],
            "expected_fields": ["title", "canonical_url", "published_at"],
            "risk": {
                "terms": 0,
                "authentication": 0,
                "stability": 0,
                "data_quality": 0,
                "operating_cost": 0,
            },
            "ingestion": {
                "enabled": True,
                "approved_at": "2026-07-18T00:00:00Z",
            },
        }
    )


def _autopilot_lease(run_id: int, stage: DailyAutopilotStage) -> OperationLease:
    return OperationLease(
        operation_id=run_id,
        attempt_id=1,
        attempt_number=1,
        worker_id="acceptance-worker",
        operation_type=OperationType.DAILY_AUTOPILOT.value,
        requested_scope={"daily_autopilot_run_id": run_id, "stage": stage.value},
    )


def test_daily_autopilot_turns_real_wave_items_into_reviewed_dual_audio_package(
    tmp_path,
    monkeypatch,
) -> None:
    now = datetime.now(UTC)
    safe_settings = Settings(_env_file=None, minimax_api_key=None, operation_timeout_seconds=60)
    monkeypatch.setattr("newsradar.operations.commands.get_settings", lambda: safe_settings)
    monkeypatch.setattr("newsradar.events.pipeline.get_settings", lambda: safe_settings)
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'autopilot-acceptance.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    sources = (_source("official-alpha"), _source("official-beta"), _source("broken-feed"))

    with factory() as db:
        for source in sources:
            _, definition_hash = canonical_definition(source)
            db.add(
                SourceDefinitionRecord(
                    id=source.id,
                    name=source.name,
                    provider_id=source.provider_id,
                    status="active",
                    nature="first_party",
                    language="en",
                    roles=["discovery", "evidence"],
                    topics=["ai"],
                    authority_score=5,
                    poll_interval_minutes=60,
                    expected_fields=["title", "canonical_url", "published_at"],
                    definition_hash=definition_hash,
                )
            )
        db.commit()
        plan = wave_plan_from_members(
            profile_id="acceptance",
            members=tuple(
                WaveMemberSnapshot(
                    source_id=source.id,
                    provider_id=source.provider_id,
                    definition_hash=canonical_definition(source)[1],
                    roles=("discovery", "evidence"),
                    availability="ready",
                    access_kind="rss",
                    fetchable=True,
                    blocked_reason=None,
                    nature="first_party",
                )
                for source in sources
            ),
            window_hours=24,
            trend_days=7,
        )
        run_id = OperationCommandService(
            db, utcnow=lambda: now, settings=safe_settings
        ).enqueue_daily_autopilot(plan=plan, trigger="acceptance")

    autopilot = DailyAutopilotHandler(factory)
    enqueue_result = autopilot(
        _autopilot_lease(run_id, DailyAutopilotStage.ENQUEUE_CONTENT_WAVE),
        lambda _boundary: None,
    )
    assert enqueue_result.status is OperationStatus.SUCCEEDED
    with factory() as db:
        run = DailyAutopilotRepository(db).get(run_id)
        assert run.event_operation_id is not None
        wave_id = run.event_operation_id
        wave = db.get(OperationRunRecord, wave_id)
        assert wave is not None
        wave_scope = dict(wave.requested_scope)

    write_lock = Lock()

    def execute(source, operation_id, checkpoint, _scope):
        checkpoint(f"acceptance_fetch:{source.id}")
        if source.id == "broken-feed":
            return SourceFetchSummary(
                source.id,
                FetchResult(
                    outcome=FetchOutcome.FAILED,
                    error_code="network_unavailable",
                    error_message="测试来源不可用",
                ),
            )
        with write_lock, factory() as db:
            fetch = FetchRunRecord(
                source_id=source.id,
                operation_run_id=operation_id,
                outcome=FetchOutcome.SUCCEEDED.value,
                items_received=1,
                items_inserted=1,
                items_updated=0,
                items_unchanged=0,
                started_at=now,
                finished_at=now,
            )
            db.add(fetch)
            db.flush()
            db.add(
                RawItemRecord(
                    source_id=source.id,
                    external_id=f"{source.id}-1",
                    canonical_url=f"https://{source.id}.test/news/codex-agent",
                    original_url=f"https://{source.id}.test/news/codex-agent",
                    payload={},
                    title="OpenAI releases Codex AI agent model with new safety controls",
                    summary="OpenAI released an AI coding agent and documented safety controls.",
                    language="en",
                    content_type="article",
                    published_at=now,
                    fetched_at=now,
                    first_seen_run_id=fetch.id,
                    last_seen_run_id=fetch.id,
                )
            )
            db.commit()
            fetch_id = fetch.id
        return SourceFetchSummary(
            source.id,
            FetchResult(
                outcome=FetchOutcome.SUCCEEDED,
                items_received=1,
                items_inserted=1,
            ),
            fetch_run_id=fetch_id,
        )

    wave_result = HighValueWaveHandler(sources, factory, execute)(
        OperationLease(
            operation_id=wave_id,
            attempt_id=1,
            attempt_number=1,
            worker_id="acceptance-worker",
            operation_type=OperationType.HIGH_VALUE_NEWS_WAVE.value,
            requested_scope=wave_scope,
        ),
        lambda _boundary: None,
    )
    assert wave_result.status is OperationStatus.PARTIAL
    assert wave_result.result_summary["event_manifest_complete"] is True
    assert wave_result.result_summary["event_manifest_count"] > 0
    with factory() as db:
        wave = db.get(OperationRunRecord, wave_id)
        assert wave is not None
        wave.status = wave_result.status.value
        wave.result_summary = dict(wave_result.result_summary)
        wave.finished_at = datetime.now(UTC)
        db.commit()

    for stage in (
        DailyAutopilotStage.WAIT_CONTENT_WAVE,
        DailyAutopilotStage.GENERATE_REPORT,
        DailyAutopilotStage.WRITE_REVIEWS,
        DailyAutopilotStage.ARCHIVE_AND_ENQUEUE_AUDIO,
    ):
        result = autopilot(_autopilot_lease(run_id, stage), lambda _boundary: None)
        assert result.status is OperationStatus.SUCCEEDED

    with factory() as db:
        run = DailyAutopilotRepository(db).get(run_id)
        report = db.get(DailyReportRecord, run.daily_report_id)
        repository = DailyReportRepository(db)
        assert report is not None
        assert report.status == "archived"
        assert report.source_operation_id == wave_id
        assert report.generation_summary["overview_count"] > 0
        assert db.scalar(
            select(func.count()).select_from(FetchRunRecord).where(
                FetchRunRecord.operation_run_id == wave_id
            )
        ) == 2
        assert db.scalar(select(func.count()).select_from(RawItemRecord)) > 0
        assert all(repository.editorial_reviews(item.id) for item in repository.items(report.id))
        assert all(
            repository.overview_editorial_reviews(item.id)
            for item in repository.overview_items(report.id)
        )
        queued = tuple(
            db.scalars(
                select(OperationRunRecord).where(
                    OperationRunRecord.operation_type
                    == OperationType.DAILY_REPORT_AUDIO.value
                )
            )
        )
        assert {row.requested_scope["rendition"] for row in queued} == {
            "decision",
            "overview",
        }
        members = {
            row.source_id: row.state
            for row in db.scalars(
                select(HighValueWaveMemberRecord).where(
                    HighValueWaveMemberRecord.operation_run_id == wave_id
                )
            )
        }
        assert members["broken-feed"] == "failed"
        assert run.stage == DailyAutopilotStage.WAIT_AUDIO.value
    engine.dispose()
