from __future__ import annotations

import asyncio
from dataclasses import replace
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
from newsradar.providers.repository import canonical_provider
from newsradar.providers.schema import Availability, ProviderDefinition
from newsradar.sources.catalog_refresh import (
    CatalogMemberState,
    CatalogRefreshLane,
    CatalogRefreshMemberSnapshot,
    CatalogRefreshPlan,
    CatalogResultCode,
    catalog_definition_hash,
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
    source_id: str,
    provider_id: str = "provider-a",
    availability: str = "requires_credentials",
) -> CatalogRefreshMemberSnapshot:
    payload = valid_provider()
    payload["id"] = provider_id
    provider_hash = canonical_provider(ProviderDefinition.model_validate(payload))[1]
    return CatalogRefreshMemberSnapshot(
        source_id=source_id,
        provider_id=provider_id,
        definition_hash="hash",
        availability=availability,
        coverage_mode="direct",
        access_kind="public_api",
        lane=CatalogRefreshLane.CAPABILITY,
        provider_definition_hash=provider_hash,
    )


def frozen_member(definition, provider, lane, availability="ready", access_kind="rss"):
    return CatalogRefreshMemberSnapshot(
        source_id=definition.id,
        provider_id=definition.provider_id,
        definition_hash=catalog_definition_hash(definition, {provider.id} if provider else set()),
        availability=availability,
        coverage_mode="direct",
        access_kind=access_kind,
        lane=lane,
        provider_definition_hash=canonical_provider(provider)[1] if provider else None,
    )


def provider_for(definition: SourceDefinition) -> ProviderDefinition:
    payload = valid_provider()
    payload["id"] = definition.provider_id
    return ProviderDefinition.model_validate(payload)


def content_member(definition: SourceDefinition) -> CatalogRefreshMemberSnapshot:
    return frozen_member(definition, provider_for(definition), CatalogRefreshLane.CONTENT)


def catalog_member(source_id: str) -> CatalogRefreshMemberSnapshot:
    provider_hash = canonical_provider(ProviderDefinition.model_validate(valid_provider()))[1]
    return CatalogRefreshMemberSnapshot(
        source_id=source_id,
        provider_id="provider-a",
        definition_hash="hash",
        availability="manual_only",
        coverage_mode="catalog_only",
        access_kind="html",
        lane=CatalogRefreshLane.CATALOG,
        provider_definition_hash=provider_hash,
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
    return CatalogRefreshHandler(
        [definition], [provider_for(definition)], lambda: db_session, probe_factory=probe
    )


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
            1,
            CatalogRefreshPlan.from_members(
                [
                    frozen_member(
                        first,
                        provider,
                        CatalogRefreshLane.CAPABILITY,
                        "requires_credentials",
                        "public_api",
                    ),
                    frozen_member(
                        second,
                        provider,
                        CatalogRefreshLane.CAPABILITY,
                        "requires_credentials",
                        "public_api",
                    ),
                ]
            ),
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
        provider_payload = valid_provider()
        provider_payload["id"] = definition.provider_id
        provider = ProviderDefinition.model_validate(provider_payload)
        CatalogRefreshRepository(db_session).create_members(
            1,
            CatalogRefreshPlan.from_members(
                [
                    frozen_member(
                        definition, provider, CatalogRefreshLane.CATALOG, "manual_only", "html"
                    )
                ]
            ),
        )
        db_session.commit()
        content_probe = RecordingProbe([result()])
        handler = CatalogRefreshHandler(
            [definition], [provider], lambda: db_session, probe_factory=content_probe
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


def test_transient_content_timeout_retries_once_then_completes_three_rounds() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        definition = source()
        add_member(
            db_session,
            content_member(definition),
        )
        probe = RecordingProbe([result(error_code="timeout"), result(), result(), result()])

        outcome = make_handler(db_session, definition, probe).run_content_member(
            1, "feed", lambda _: None
        )

        assert probe.calls == 4
        assert outcome.state is CatalogMemberState.SUCCEEDED


def test_second_transient_content_failure_stops_after_one_retry() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        definition = source()
        add_member(
            db_session,
            content_member(definition),
        )
        probe = RecordingProbe(
            [result(error_code="connection_error"), result(error_code="timeout")]
        )

        outcome = make_handler(db_session, definition, probe).run_content_member(
            1, "feed", lambda _: None
        )

        assert probe.calls == 2
        assert outcome.state is CatalogMemberState.FAILED
        assert outcome.result_code is CatalogResultCode.TIMEOUT


def test_retry_after_beyond_deadline_records_rate_limit_without_retry() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        definition = source()
        add_member(
            db_session,
            content_member(definition),
        )
        limited = result(http_status=429)
        limited.response_headers = {"Retry-After": "120"}
        probe = RecordingProbe([limited, result()])

        operation = make_handler(db_session, definition, probe)(
            OperationLease(
                1,
                1,
                1,
                "worker",
                {"deadline_at": (datetime.now(UTC) + timedelta(seconds=1)).isoformat()},
                "source_catalog_refresh",
            ),
            lambda _: None,
        )

        assert probe.calls == 1
        assert operation.status.value == "partial"
        stored = db_session.scalar(select(SourceCatalogRefreshMemberRecord))
        assert stored is not None
        assert stored.result_code == CatalogResultCode.RATE_LIMITED.value


def test_capability_exception_is_persisted_and_other_provider_continues() -> None:
    class FlakyProviderProbe:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def __call__(self, provider: ProviderDefinition) -> ProviderProbeResult:
            self.calls.append(provider.id)
            if provider.id == "provider-a":
                raise RuntimeError("transport broke")
            return ProviderProbeResult(
                provider_id=provider.id,
                outcome="blocked",
                availability=provider.availability.value,
                reason="approval required",
                checked_at=datetime.now(UTC),
                evidence_url=str(provider.docs_url),
            )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        provider_payload = valid_provider()
        provider_payload["id"] = "provider-a"
        first = ProviderDefinition.model_validate(provider_payload)
        provider_payload["id"] = "provider-b"
        second = ProviderDefinition.model_validate(provider_payload)
        definitions = [source("a", "provider-a"), source("b", "provider-b")]
        CatalogRefreshRepository(db_session).create_members(
            1,
            CatalogRefreshPlan.from_members(
                [
                    frozen_member(
                        definitions[0], first, CatalogRefreshLane.CAPABILITY, "ready", "public_api"
                    ),
                    frozen_member(
                        definitions[1],
                        second,
                        CatalogRefreshLane.CAPABILITY,
                        "requires_credentials",
                        "public_api",
                    ),
                ]
            ),
        )
        db_session.commit()
        provider_probe = FlakyProviderProbe()
        handler = CatalogRefreshHandler(
            definitions,
            [first, second],
            lambda: db_session,
            provider_probe_factory=provider_probe,
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
        assert provider_probe.calls == ["provider-a", "provider-b"]
        records = db_session.scalars(
            select(SourceCatalogRefreshMemberRecord).order_by(
                SourceCatalogRefreshMemberRecord.source_id
            )
        ).all()
        assert records[0].state == CatalogMemberState.FAILED.value
        assert records[1].state == CatalogMemberState.BLOCKED.value


def test_content_member_runs_three_serial_probes_after_first_success() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        definition = source()
        snapshot = content_member(definition)
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
            content_member(definition),
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
        add_member(
            db_session, replace(content_member(definition), definition_hash="old-definition")
        )
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


def test_provider_drift_in_content_lane_finishes_stale_without_network_call() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        definition = source()
        provider_payload = valid_provider()
        provider_payload["id"] = definition.provider_id
        frozen_provider = ProviderDefinition.model_validate(provider_payload)
        add_member(
            db_session,
            frozen_member(definition, frozen_provider, CatalogRefreshLane.CONTENT),
        )
        current_provider = frozen_provider.model_copy(
            update={"name": "Provider definition changed after freeze"}
        )
        probe = RecordingProbe([result()])

        outcome = CatalogRefreshHandler(
            [definition], [current_provider], lambda: db_session, probe_factory=probe
        ).run_content_member(1, "feed", lambda _: None)

        assert probe.calls == 0
        assert outcome.state is CatalogMemberState.DEGRADED
        assert outcome.result_code is CatalogResultCode.STALE_RESULT


def test_old_null_provider_hash_in_content_lane_finishes_stale_without_network_call() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        definition = source()
        add_member(db_session, replace(content_member(definition), provider_definition_hash=None))
        probe = RecordingProbe([result()])

        outcome = make_handler(db_session, definition, probe).run_content_member(
            1, "feed", lambda _: None
        )

        assert probe.calls == 0
        assert outcome.result_code is CatalogResultCode.STALE_RESULT


def test_capability_source_drift_finishes_stale_without_provider_probe() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        frozen = source()
        provider = provider_for(frozen)
        add_member(
            db_session,
            frozen_member(
                frozen,
                provider,
                CatalogRefreshLane.CAPABILITY,
                "requires_credentials",
                "public_api",
            ),
        )
        changed = frozen.model_copy(update={"name": "Source changed after freeze"})
        provider_probe = RecordingProviderProbe()
        lease = OperationLease(
            1,
            1,
            1,
            "test",
            {"deadline_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat()},
            "source_catalog_refresh",
        )

        CatalogRefreshHandler(
            [changed], [provider], lambda: db_session, provider_probe_factory=provider_probe
        )(lease, lambda _: None)

        assert provider_probe.calls == 0
        stored = db_session.scalar(select(SourceCatalogRefreshMemberRecord))
        assert stored is not None and stored.result_code == CatalogResultCode.STALE_RESULT.value


def test_catalog_source_drift_finishes_stale_without_catalog_validation(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        frozen = source("catalog")
        provider = provider_for(frozen)
        add_member(
            db_session,
            frozen_member(frozen, provider, CatalogRefreshLane.CATALOG, "manual_only", "html"),
        )
        changed = frozen.model_copy(update={"name": "Source changed after freeze"})
        validation_calls: list[str] = []
        monkeypatch.setattr(
            "newsradar.sources.catalog_refresh_runtime.validate_catalog_entry",
            lambda source, provider: validation_calls.append(source.id),
        )
        lease = OperationLease(
            1,
            1,
            1,
            "test",
            {"deadline_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat()},
            "source_catalog_refresh",
        )

        CatalogRefreshHandler([changed], [provider], lambda: db_session)(lease, lambda _: None)

        assert validation_calls == []
        stored = db_session.scalar(select(SourceCatalogRefreshMemberRecord))
        assert stored is not None and stored.result_code == CatalogResultCode.STALE_RESULT.value


def test_already_claimed_content_member_performs_no_network_io() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        definition = source()
        add_member(db_session, content_member(definition))
        CatalogRefreshRepository(db_session).start_member(1, definition.id)
        db_session.commit()
        probe = RecordingProbe([result()])

        outcome = make_handler(db_session, definition, probe).run_content_member(
            1, definition.id, lambda _: None
        )

        assert probe.calls == 0
        assert outcome.state is CatalogMemberState.RUNNING


def test_catalog_loop_cancellation_propagates_before_next_member_validation(monkeypatch) -> None:
    class CheckpointCancelled(Exception):
        pass

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        first, second = source("a"), source("b")
        provider = provider_for(first)
        CatalogRefreshRepository(db_session).create_members(
            1,
            CatalogRefreshPlan.from_members(
                [
                    frozen_member(
                        first, provider, CatalogRefreshLane.CATALOG, "manual_only", "html"
                    ),
                    frozen_member(
                        second, provider, CatalogRefreshLane.CATALOG, "manual_only", "html"
                    ),
                ]
            ),
        )
        db_session.commit()
        validations: list[str] = []
        monkeypatch.setattr(
            "newsradar.sources.catalog_refresh_runtime.validate_catalog_entry",
            lambda source, provider: validations.append(source.id) or type(
                "Validation", (), {"code": CatalogResultCode.CATALOG_VERIFIED, "conclusion": "ok"}
            )(),
        )
        lease = OperationLease(
            1,
            1,
            1,
            "test",
            {"deadline_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat()},
            "source_catalog_refresh",
        )

        with pytest.raises(CheckpointCancelled):
            CatalogRefreshHandler([first, second], [provider], lambda: db_session)(
                lease,
                lambda point: (
                    (_ for _ in ()).throw(CheckpointCancelled())
                    if point == "after_catalog_member:a"
                    else None
                ),
            )

        assert validations == ["a"]
        records = db_session.scalars(
            select(SourceCatalogRefreshMemberRecord).order_by(SourceCatalogRefreshMemberRecord.source_id)
        ).all()
        assert [record.state for record in records] == ["succeeded", "pending"]


def test_removed_definition_finishes_stale_without_network_call() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        definition = source()
        add_member(
            db_session,
            content_member(definition),
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
            content_member(definition),
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
            content_member(definition),
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
        providers = {item.provider_id: provider_for(item) for item in definitions}
        snapshots = [
            frozen_member(item, providers[item.provider_id], CatalogRefreshLane.CONTENT)
            for item in definitions
        ]
        CatalogRefreshRepository(db_session).create_members(
            1, CatalogRefreshPlan.from_members(snapshots)
        )
        db_session.commit()
        probe = ConcurrentProbe()
        handler = CatalogRefreshHandler(
            definitions, providers.values(), lambda: db_session, probe_factory=probe
        )
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
