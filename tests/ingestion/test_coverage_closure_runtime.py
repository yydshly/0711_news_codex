from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import Base, FetchRunRecord, OperationRunRecord, RawItemRecord
from newsradar.ingestion.coverage_closure_runtime import (
    COVERAGE_CLOSURE_TRIGGER,
    ClosureOperation,
    CoverageClosureService,
)
from newsradar.sources.probes.base import ProbeOutcome, ProbeResult, ProbeSample
from newsradar.sources.repository import SourceRepository
from newsradar.sources.schema import SourceDefinition
from tests.test_source_schema import valid_source


def _source(source_id: str, **changes: object) -> SourceDefinition:
    values = valid_source()
    values.update({"id": source_id, "name": source_id, **changes})
    return SourceDefinition.model_validate(values)


def _save_successful_probe(session: Session, source: SourceDefinition) -> None:
    finished_at = datetime(2026, 7, 14, tzinfo=UTC)
    SourceRepository(session).save_probe_result(
        ProbeResult(
            source_id=source.id,
            access_kind="rss",
            access_url="https://example.test/feed.xml",
            outcome=ProbeOutcome.SUCCESS,
            started_at=finished_at,
            finished_at=finished_at,
            sample_count=1,
            field_completeness=1.0,
            samples=[
                ProbeSample(
                    external_id=source.id,
                    title=source.name,
                    canonical_url=f"https://example.test/{source.id}",
                )
            ],
            suggested_status="candidate",
            reason="ok",
        )
    )


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_service_counts_only_succeeded_and_no_change_as_covered() -> None:
    sources = [_source(name) for name in ("succeeded", "unchanged", "partial", "failed")]
    with _session() as session:
        SourceRepository(session).sync(sources)
        for source in sources:
            _save_successful_probe(session, source)
        for source_id, outcome in (
            ("succeeded", "succeeded"),
            ("unchanged", "no_change"),
            ("partial", "partial"),
            ("failed", "failed"),
        ):
            session.add(FetchRunRecord(source_id=source_id, outcome=outcome))
        session.commit()

        plan = CoverageClosureService(session).plan(sources)

    assert {item.source_id for item in plan.covered} == {"succeeded", "unchanged"}
    assert {item.source_id for item in plan.queueable} == {"partial", "failed"}


def test_service_does_not_queue_covered_blocked_or_active_sources() -> None:
    sources = [
        _source("covered"),
        _source("queueable"),
        _source(
            "blocked",
            access_methods=[
                {
                    "kind": "rss",
                    "url": "https://example.test/blocked.xml",
                    "priority": 1,
                    "headers": {"Authorization": "Bearer test"},
                }
            ],
        ),
        _source("active"),
    ]
    calls: list[dict[str, object]] = []

    class Commands:
        def enqueue_fetch(self, **kwargs: object) -> int:
            calls.append(kwargs)
            return 41

    with _session() as session:
        SourceRepository(session).sync(sources)
        for source in sources:
            _save_successful_probe(session, source)
        session.add(FetchRunRecord(source_id="covered", outcome="succeeded"))
        session.add(
            OperationRunRecord(
                operation_type="fetch",
                trigger="cli",
                status="queued",
                requested_scope={"source_id": "active"},
                result_summary={},
                attempt_count=0,
            )
        )
        session.commit()
        service = CoverageClosureService(session, commands_factory=lambda _: Commands())
        plan = service.plan(sources)
        operations = service.enqueue(plan, max_items=5, trigger="cli")

    assert [(item.source_id, item.operation_id) for item in operations] == [("queueable", 41)]
    assert calls == [
        {
            "source_id": "queueable",
            "max_items": 5,
            "trial": True,
            "trigger": "cli",
        }
    ]


def test_service_records_enqueue_failure_and_continues_with_later_source() -> None:
    sources = [_source("first"), _source("second")]

    class Commands:
        def enqueue_fetch(self, **kwargs: object) -> int:
            if kwargs["source_id"] == "first":
                raise ValueError("duplicate operation")
            return 42

    with _session() as session:
        SourceRepository(session).sync(sources)
        for source in sources:
            _save_successful_probe(session, source)
        session.commit()
        service = CoverageClosureService(session, commands_factory=lambda _: Commands())
        operations = service.enqueue(service.plan(sources), max_items=5, trigger="cli")

    assert [(item.source_id, item.operation_id, item.status) for item in operations] == [
        ("first", 0, "enqueue_failed"),
        ("second", 42, None),
    ]


def test_enqueue_rechecks_active_source_after_acquiring_source_lock(monkeypatch) -> None:
    source = _source("queueable")
    calls: list[dict[str, object]] = []
    locks: list[str] = []

    class Commands:
        def enqueue_fetch(self, **kwargs: object) -> int:
            calls.append(kwargs)
            return 42

    with _session() as session:
        SourceRepository(session).sync([source])
        _save_successful_probe(session, source)
        session.commit()
        service = CoverageClosureService(session, commands_factory=lambda _: Commands())
        plan = service.plan([source])
        monkeypatch.setattr(
            service,
            "_lock_source_for_enqueue",
            lambda source_id: locks.append(source_id) or True,
        )
        monkeypatch.setattr(service, "_active_source_ids", lambda: {source.id})

        operations = service.enqueue(plan, max_items=5, trigger="cli")

    assert locks == [source.id]
    assert calls == []
    assert operations == (ClosureOperation(source.id, 0, "operation_in_progress"),)


def test_evidence_returns_latest_outcome_and_raw_item_count() -> None:
    source = _source("evidence")
    with _session() as session:
        SourceRepository(session).sync([source])
        session.add(
            FetchRunRecord(
                source_id=source.id,
                outcome="failed",
                error_code="rate_limited",
            )
        )
        session.add(FetchRunRecord(source_id=source.id, outcome="succeeded"))
        for index in range(2):
            session.add(
                RawItemRecord(
                    source_id=source.id,
                    external_id=f"item-{index}",
                    canonical_url=f"https://example.test/items/{index}",
                    payload={},
                )
            )
        session.commit()

        evidence = CoverageClosureService(session).evidence([source.id])

    assert [
        (item.source_id, item.latest_fetch_outcome, item.raw_item_count)
        for item in evidence
    ] == [("evidence", "succeeded", 2)]


def test_operation_evidence_excludes_other_fetches_and_counts_only_this_runs_new_items() -> None:
    source = _source("evidence")
    with _session() as session:
        SourceRepository(session).sync([source])
        operation = OperationRunRecord(
            operation_type="fetch",
            trigger="cli",
            status="succeeded",
            requested_scope={"source_id": source.id},
            result_summary={},
            attempt_count=0,
        )
        other_operation = OperationRunRecord(
            operation_type="fetch",
            trigger="cli",
            status="failed",
            requested_scope={"source_id": source.id},
            result_summary={},
            attempt_count=0,
        )
        session.add_all([operation, other_operation])
        session.flush()
        own_fetch = FetchRunRecord(
            source_id=source.id,
            operation_run_id=operation.id,
            outcome="succeeded",
        )
        other_fetch = FetchRunRecord(
            source_id=source.id,
            operation_run_id=other_operation.id,
            outcome="failed",
            error_code="network_error",
        )
        session.add_all([own_fetch, other_fetch])
        session.flush()
        session.add_all(
            [
                RawItemRecord(
                    source_id=source.id,
                    external_id="own",
                    canonical_url="https://example.test/own",
                    payload={},
                    first_seen_run_id=own_fetch.id,
                ),
                RawItemRecord(
                    source_id=source.id,
                    external_id="other",
                    canonical_url="https://example.test/other",
                    payload={},
                    first_seen_run_id=other_fetch.id,
                ),
            ]
        )
        session.commit()

        evidence = CoverageClosureService(session).evidence(
            [source.id], operation_ids=[operation.id]
        )

    assert [
        (
            item.source_id,
            item.latest_fetch_outcome,
            item.latest_fetch_error_code,
            item.raw_item_count,
        )
        for item in evidence
    ] == [("evidence", "succeeded", None, 1)]


def test_wait_continues_after_missing_and_timeout_operations() -> None:
    class Commands:
        def wait_for_terminal(self, operation_id: int):
            if operation_id == 1:
                raise LookupError(operation_id)
            if operation_id == 2:
                raise TimeoutError(operation_id)
            return type("Terminal", (), {"status": "succeeded"})()

    with _session() as session:
        service = CoverageClosureService(session, commands_factory=lambda _: Commands())
        operations = service.wait(
            [
                ClosureOperation("missing", 1),
                ClosureOperation("timed-out", 2),
                ClosureOperation("completed", 3),
            ]
        )

    assert [(item.source_id, item.status) for item in operations] == [
        ("missing", "missing"),
        ("timed-out", "timed_out"),
        ("completed", "succeeded"),
    ]


def test_coverage_closure_trigger_fits_durable_operation_column() -> None:
    assert COVERAGE_CLOSURE_TRIGGER == "coverage-closure"
    assert len(COVERAGE_CLOSURE_TRIGGER) <= 16
