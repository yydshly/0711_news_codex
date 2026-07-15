from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    ProviderProbeRunRecord,
    SourceCatalogRefreshMemberRecord,
    SourceProbeRunRecord,
)
from newsradar.operations.repository import OperationLease
from newsradar.providers.probes import ProviderProbeResult
from newsradar.providers.schema import Availability, ProviderDefinition
from newsradar.sources.catalog_refresh import (
    CatalogMemberState,
    CatalogRefreshLane,
    CatalogRefreshMemberSnapshot,
    CatalogRefreshPlan,
    CatalogResultCode,
)
from newsradar.sources.catalog_refresh_repository import CatalogRefreshRepository
from newsradar.sources.catalog_refresh_runtime import (
    CatalogRefreshHandler,
    result_code_for_probe,
)
from newsradar.sources.probes.base import ProbeOutcome, ProbeResult
from newsradar.sources.schema import SourceDefinition, SourceStatus
from tests.test_provider_schema import valid_provider
from tests.test_source_schema import valid_source


def source(source_id: str = "feed", provider_id: str = "provider-a") -> SourceDefinition:
    payload = valid_source()
    payload["id"] = source_id
    payload["provider_id"] = provider_id
    return SourceDefinition.model_validate(payload)


def member(
    source_id: str = "feed", *, definition_hash: str = "hash", provider_id: str = "provider-a"
) -> CatalogRefreshMemberSnapshot:
    return CatalogRefreshMemberSnapshot(
        source_id=source_id,
        provider_id=provider_id,
        definition_hash=definition_hash,
        availability="ready",
        coverage_mode="direct",
        access_kind="rss",
        lane=CatalogRefreshLane.CONTENT,
    )


def capability_member(
    source_id: str, provider_id: str = "provider-a"
) -> CatalogRefreshMemberSnapshot:
    return CatalogRefreshMemberSnapshot(
        source_id=source_id,
        provider_id=provider_id,
        definition_hash="hash",
        availability="requires_credentials",
        coverage_mode="direct",
        access_kind="public_api",
        lane=CatalogRefreshLane.CAPABILITY,
    )


def catalog_member(source_id: str) -> CatalogRefreshMemberSnapshot:
    return CatalogRefreshMemberSnapshot(
        source_id=source_id,
        provider_id="provider-a",
        definition_hash="hash",
        availability="manual_only",
        coverage_mode="catalog_only",
        access_kind="html",
        lane=CatalogRefreshLane.CATALOG,
    )


def result(
    source_id: str = "feed", *, error_code: str | None = None, http_status: int | None = None
) -> ProbeResult:
    return ProbeResult(
        source_id=source_id,
        access_kind="rss",
        access_url="https://example.test/feed",
        outcome=ProbeOutcome.SUCCESS if error_code is None else ProbeOutcome.DEGRADED,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        http_status=http_status,
        response_headers={"Authorization": "secret", "cookie": "secret", "ETag": "safe"},
        sample_count=1 if error_code is None else 0,
        field_completeness=1.0 if error_code is None else 0.0,
        suggested_status=SourceStatus.CANDIDATE,
        reason="test",
        error_code=error_code,
    )


class RecordingProbe:
    def __init__(self, results: list[ProbeResult]) -> None:
        self.results = list(results)
        self.calls = 0

    async def __call__(self, source: SourceDefinition, method) -> ProbeResult:
        self.calls += 1
        return self.results.pop(0)


class ConcurrentProbe:
    def __init__(self) -> None:
        self.active = 0
        self.maximum = 0
        self.by_provider: dict[str, int] = {}
        self.provider_maximum: dict[str, int] = {}

    async def __call__(self, definition: SourceDefinition, method) -> ProbeResult:
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        provider_id = definition.provider_id
        self.by_provider[provider_id] = self.by_provider.get(provider_id, 0) + 1
        self.provider_maximum[provider_id] = max(
            self.provider_maximum.get(provider_id, 0), self.by_provider[provider_id]
        )
        await asyncio.sleep(0)
        self.by_provider[provider_id] -= 1
        self.active -= 1
        return result(definition.id)


class RecordingProviderProbe:
    def __init__(self, outcome: str = "blocked") -> None:
        self.calls = 0
        self.outcome = outcome

    async def __call__(self, provider) -> ProviderProbeResult:
        self.calls += 1
        return ProviderProbeResult(
            provider_id=provider.id,
            outcome=self.outcome,
            availability=provider.availability.value,
            reason="capability checked",
            checked_at=datetime.now(UTC),
            evidence_url=str(provider.docs_url),
        )


def make_handler(
    db_session: Session, definition: SourceDefinition, probe: RecordingProbe
) -> CatalogRefreshHandler:
    return CatalogRefreshHandler([definition], [], lambda: db_session, probe_factory=probe)


def add_member(db_session: Session, snapshot: CatalogRefreshMemberSnapshot) -> None:
    CatalogRefreshRepository(db_session).create_members(
        1, CatalogRefreshPlan.from_members([snapshot])
    )
    db_session.commit()


def test_capability_lane_probes_each_provider_once_and_shares_record_id() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        first, second = source("a"), source("b")
        provider_payload = valid_provider()
        provider_payload["id"] = "provider-a"
        provider_payload["availability"] = Availability.REQUIRES_CREDENTIALS.value
        provider = ProviderDefinition.model_validate(provider_payload)
        CatalogRefreshRepository(db_session).create_members(
            1, CatalogRefreshPlan.from_members([capability_member("a"), capability_member("b")])
        )
        db_session.commit()
        content_probe = RecordingProbe([result()])
        capability_probe = RecordingProviderProbe()
        handler = CatalogRefreshHandler(
            [first, second],
            [provider],
            lambda: db_session,
            probe_factory=content_probe,
            provider_probe_factory=capability_probe,
        )
        lease = OperationLease(
            1,
            1,
            1,
            "worker",
            {"deadline_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat()},
            "source_catalog_refresh",
        )

        operation = handler(lease, lambda _: None)

        assert operation.status.value == "partial"
        assert capability_probe.calls == 1
        assert content_probe.calls == 0
        stored = db_session.scalars(
            select(SourceCatalogRefreshMemberRecord).order_by(
                SourceCatalogRefreshMemberRecord.source_id
            )
        ).all()
        assert {record.state for record in stored} == {CatalogMemberState.BLOCKED.value}
        assert stored[0].provider_probe_run_id == stored[1].provider_probe_run_id
        assert len(db_session.scalars(select(ProviderProbeRunRecord)).all()) == 1


def test_catalog_lane_validates_without_any_http() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        definition = source("catalog")
        CatalogRefreshRepository(db_session).create_members(
            1, CatalogRefreshPlan.from_members([catalog_member("catalog")])
        )
        db_session.commit()
        content_probe = RecordingProbe([result()])
        handler = CatalogRefreshHandler(
            [definition], [], lambda: db_session, probe_factory=content_probe
        )
        lease = OperationLease(
            1,
            1,
            1,
            "worker",
            {"deadline_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat()},
            "source_catalog_refresh",
        )

        operation = handler(lease, lambda _: None)

        assert operation.status.value == "partial"
        assert content_probe.calls == 0
        stored = db_session.scalar(select(SourceCatalogRefreshMemberRecord))
        assert stored is not None
        assert stored.result_code == CatalogResultCode.CATALOG_INCOMPLETE.value


def test_content_member_runs_three_serial_probes_after_first_success() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        definition = source()
        snapshot = member(definition_hash=CatalogRefreshHandler.definition_hash(definition, []))
        add_member(db_session, snapshot)
        probe = RecordingProbe([result(), result(), result()])

        outcome = make_handler(db_session, definition, probe).run_content_member(
            1, "feed", lambda _: None
        )

        assert probe.calls == 3
        assert outcome.state is CatalogMemberState.SUCCEEDED
        assert len(outcome.content_probe_run_ids) == 3
        records = db_session.scalars(select(SourceProbeRunRecord)).all()
        assert len(records) == 3
        assert all(record.operation_run_id == 1 for record in records)
        assert all("Authorization" not in record.response_headers for record in records)
        assert all("cookie" not in record.response_headers for record in records)


def test_first_failed_probe_finishes_member_without_more_network_calls() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        definition = source()
        add_member(
            db_session,
            member(definition_hash=CatalogRefreshHandler.definition_hash(definition, [])),
        )
        probe = RecordingProbe([result(error_code="no_content"), result(), result()])

        outcome = make_handler(db_session, definition, probe).run_content_member(
            1, "feed", lambda _: None
        )

        assert probe.calls == 1
        assert outcome.state is CatalogMemberState.DEGRADED
        assert outcome.result_code is CatalogResultCode.NO_CONTENT
        assert len(outcome.content_probe_run_ids) == 1


def test_definition_drift_finishes_stale_without_network_call() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        definition = source()
        add_member(db_session, member(definition_hash="old-definition"))
        probe = RecordingProbe([result()])

        outcome = make_handler(db_session, definition, probe).run_content_member(
            1, "feed", lambda _: None
        )

        assert probe.calls == 0
        assert outcome.state is CatalogMemberState.DEGRADED
        assert outcome.result_code is CatalogResultCode.STALE_RESULT
        stored = db_session.scalar(select(SourceCatalogRefreshMemberRecord))
        assert stored is not None
        assert stored.conclusion == "批次创建后来源定义已变化"


def test_removed_definition_finishes_stale_without_network_call() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        definition = source()
        add_member(
            db_session,
            member(definition_hash=CatalogRefreshHandler.definition_hash(definition, [])),
        )
        probe = RecordingProbe([result()])

        outcome = CatalogRefreshHandler(
            [], [], lambda: db_session, probe_factory=probe
        ).run_content_member(1, "feed", lambda _: None)

        assert probe.calls == 0
        assert outcome.state is CatalogMemberState.DEGRADED
        assert outcome.result_code is CatalogResultCode.STALE_RESULT
        assert outcome.conclusion == "批次创建后来源定义已变化"


def test_archived_definition_after_freeze_finishes_stale_without_network_call() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        definition = source()
        add_member(
            db_session,
            member(definition_hash=CatalogRefreshHandler.definition_hash(definition, [])),
        )
        object.__setattr__(definition, "catalog_state", "archived")
        probe = RecordingProbe([result()])

        outcome = make_handler(db_session, definition, probe).run_content_member(
            1, "feed", lambda _: None
        )

        assert probe.calls == 0
        assert outcome.state is CatalogMemberState.DEGRADED
        assert outcome.result_code is CatalogResultCode.STALE_RESULT
        assert outcome.conclusion == "批次创建后来源定义已变化"


def test_checkpoint_cancellation_propagates_without_becoming_internal_error() -> None:
    class CheckpointCancelled(Exception):
        pass

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        definition = source()
        add_member(
            db_session,
            member(definition_hash=CatalogRefreshHandler.definition_hash(definition, [])),
        )
        probe = RecordingProbe([result()])

        lease = OperationLease(
            operation_id=1,
            attempt_id=1,
            attempt_number=1,
            worker_id="test",
            operation_type="source_catalog_refresh",
            requested_scope={"deadline_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat()},
        )
        with pytest.raises(CheckpointCancelled):
            make_handler(db_session, definition, probe)(
                lease,
                lambda _: (_ for _ in ()).throw(CheckpointCancelled()),
            )

        assert probe.calls == 0


def test_probe_error_codes_have_stable_catalog_mapping() -> None:
    assert (
        result_code_for_probe(result(error_code="incomplete_fields"))
        is CatalogResultCode.INCOMPLETE_FIELDS
    )
    assert result_code_for_probe(result(error_code="timeout")) is CatalogResultCode.TIMEOUT
    assert (
        result_code_for_probe(result(error_code="missing_credential"))
        is CatalogResultCode.MISSING_CREDENTIALS
    )
    assert result_code_for_probe(result(http_status=429)) is CatalogResultCode.RATE_LIMITED
    assert (
        result_code_for_probe(result(error_code="unsupported_access_kind"))
        is CatalogResultCode.UNSUPPORTED_ACCESS_KIND
    )


def test_batch_keeps_global_and_provider_content_concurrency_bounded() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        definitions = [
            source(f"source-{index}", "provider-a" if index < 3 else "provider-b")
            for index in range(6)
        ]
        snapshots = [
            member(
                item.id,
                provider_id=item.provider_id,
                definition_hash=CatalogRefreshHandler.definition_hash(item, []),
            )
            for item in definitions
        ]
        CatalogRefreshRepository(db_session).create_members(
            1, CatalogRefreshPlan.from_members(snapshots)
        )
        db_session.commit()
        probe = ConcurrentProbe()
        handler = CatalogRefreshHandler(definitions, [], lambda: db_session, probe_factory=probe)
        lease = OperationLease(
            operation_id=1,
            attempt_id=1,
            attempt_number=1,
            worker_id="test",
            operation_type="source_catalog_refresh",
            requested_scope={
                "deadline_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
                "global_concurrency": 3,
                "provider_concurrency": 2,
            },
        )

        operation = handler(lease, lambda _: None)

        assert operation.status.value == "succeeded"
        assert probe.maximum <= 3
        assert all(count <= 2 for count in probe.provider_maximum.values())
