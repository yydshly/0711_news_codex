from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from json import dumps

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import Base, OperationRunRecord, SourceCatalogRefreshMemberRecord
from newsradar.operations.commands import OperationCommandService
from newsradar.settings import Settings
from newsradar.sources.catalog_refresh import (
    CatalogMemberState,
    CatalogRefreshLane,
    CatalogRefreshMemberSnapshot,
    CatalogRefreshPlan,
    CatalogResultCode,
)
from newsradar.sources.catalog_refresh_repository import CatalogRefreshRepository
from newsradar.waves import WaveMemberSnapshot, WavePlan
from newsradar.waves.repository import WaveRepository


def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def catalog_plan(*members: CatalogRefreshMemberSnapshot) -> CatalogRefreshPlan:
    return CatalogRefreshPlan.from_members(members)


def catalog_member(
    source_id: str,
    *,
    lane: CatalogRefreshLane = CatalogRefreshLane.CONTENT,
) -> CatalogRefreshMemberSnapshot:
    return CatalogRefreshMemberSnapshot(
        source_id=source_id,
        provider_id="provider",
        definition_hash=f"hash-{source_id}",
        availability="ready",
        coverage_mode="direct",
        access_kind="rss",
        lane=lane,
    )


def wave_plan(*members: WaveMemberSnapshot) -> WavePlan:
    return WavePlan("high-value", tuple(members), "wave-digest", 24, 7)


def wave_member(source_id: str, *, fetchable: bool = True) -> WaveMemberSnapshot:
    return WaveMemberSnapshot(
        source_id, "provider", f"hash-{source_id}", ("discovery",), "ready", "rss", fetchable, None
    )


def test_enqueue_wave_freezes_plan_atomically() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    with session() as db:
        operation_id = OperationCommandService(
            db, utcnow=lambda: now, settings=Settings(operation_timeout_seconds=30)
        ).enqueue_high_value_wave(plan=wave_plan(wave_member("b"), wave_member("a")), trigger="web")
        operation = db.get(OperationRunRecord, operation_id)
        assert operation is not None
        assert operation.operation_type == "high_value_news_wave"
        assert operation.progress_total == 2
        assert operation.requested_scope == {
            "schema_version": 1,
            "profile_id": "high-value",
            "profile_digest": "wave-digest",
            "member_count": 2,
            "window_hours": 24,
            "trend_days": 7,
            "window_end": now.isoformat(),
            "algorithm_versions": {
                "relevance": "relevance-v2",
                "newsworthiness": "newsworthiness-v2",
                "entities": "entities-v2",
                "cluster": "cluster-v2",
                "score": "score-v2",
            },
            "deadline_at": "2026-07-16T12:00:30+00:00",
        }
        assert [row.source_id for row in WaveRepository(db).members(operation_id)] == ["a", "b"]


def test_enqueue_wave_rejects_active_batch_and_rolls_back_member_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with session() as db:
        service = OperationCommandService(db)
        service.enqueue_high_value_wave(plan=wave_plan(wave_member("a")), trigger="web")
        with pytest.raises(ValueError, match="active_high_value_wave_exists"):
            service.enqueue_high_value_wave(plan=wave_plan(wave_member("b")), trigger="web")

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("freeze failed")

    monkeypatch.setattr(WaveRepository, "create_members", fail)
    with session() as db:
        with pytest.raises(RuntimeError, match="freeze failed"):
            OperationCommandService(db).enqueue_high_value_wave(
                plan=wave_plan(wave_member("a")), trigger="web"
            )
        assert db.query(OperationRunRecord).count() == 0


def test_enqueue_all_blocked_wave_starts_at_zero_and_is_worker_claimable() -> None:
    with session() as db:
        operation_id = OperationCommandService(db).enqueue_high_value_wave(
            plan=wave_plan(wave_member("blocked", fetchable=False)), trigger="web"
        )

        operation = db.get(OperationRunRecord, operation_id)
        assert operation is not None
        assert (operation.progress_current, operation.progress_total) == (0, 1)
        member, claimed = WaveRepository(db).claim_member(
            operation_id, "blocked", claim_attempt_id=1
        )
        assert claimed is True
        assert member.state == "running"


def test_enqueue_catalog_refresh_freezes_members_and_scope() -> None:
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    with session() as db:
        service = OperationCommandService(
            db,
            utcnow=lambda: now,
            settings=Settings(operation_timeout_seconds=30),
        )
        plan = catalog_plan(
            catalog_member("b", lane=CatalogRefreshLane.CATALOG),
            catalog_member("a"),
        )

        operation_id = service.enqueue_source_catalog_refresh(plan, trigger="cli")
        assert not db.in_transaction()

        record = db.get(OperationRunRecord, operation_id)
        assert record is not None
        assert record.operation_type == "source_catalog_refresh"
        assert record.progress_total == 2
        assert record.requested_scope == {
            "schema_version": 1,
            "catalog_digest": plan.catalog_digest,
            "catalog_count": 2,
            "requested_lanes": ["catalog", "content"],
            "global_concurrency": 8,
            "provider_concurrency": 2,
            "deadline_at": "2026-07-15T12:00:30+00:00",
        }
        members = list(
            db.query(SourceCatalogRefreshMemberRecord)
            .filter_by(operation_run_id=operation_id)
            .order_by(SourceCatalogRefreshMemberRecord.source_id)
        )
        assert [member.source_id for member in members] == ["a", "b"]


@pytest.mark.parametrize(
    "global_concurrency,provider_concurrency", [(0, 2), (17, 2), (8, 0), (8, 9)]
)
def test_enqueue_catalog_refresh_rejects_invalid_concurrency(
    global_concurrency: int, provider_concurrency: int
) -> None:
    with session() as db:
        with pytest.raises(ValueError, match="invalid_catalog_refresh_concurrency"):
            OperationCommandService(db).enqueue_source_catalog_refresh(
                catalog_plan(catalog_member("a")),
                trigger="cli",
                global_concurrency=global_concurrency,
                provider_concurrency=provider_concurrency,
            )


def test_enqueue_catalog_refresh_rejects_active_operation_without_members() -> None:
    with session() as db:
        service = OperationCommandService(db)
        first_id = service.enqueue_source_catalog_refresh(
            catalog_plan(catalog_member("a")), trigger="cli"
        )

        with pytest.raises(ValueError, match="active_catalog_refresh_exists"):
            service.enqueue_source_catalog_refresh(catalog_plan(catalog_member("b")), trigger="cli")

        assert (
            db.query(SourceCatalogRefreshMemberRecord).filter_by(operation_run_id=first_id).count()
            == 1
        )
        assert db.query(SourceCatalogRefreshMemberRecord).filter_by(source_id="b").count() == 0


def test_enqueue_catalog_refresh_removes_operation_when_member_freeze_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_member_freeze(*args: object, **kwargs: object) -> None:
        raise RuntimeError("member freeze failed")

    monkeypatch.setattr(CatalogRefreshRepository, "create_members", fail_member_freeze)
    with session() as db:
        with pytest.raises(RuntimeError, match="member freeze failed"):
            OperationCommandService(db).enqueue_source_catalog_refresh(
                catalog_plan(catalog_member("a")), trigger="cli"
            )

        assert db.query(OperationRunRecord).count() == 0
        assert db.query(SourceCatalogRefreshMemberRecord).count() == 0


def test_retry_catalog_refresh_only_copies_transient_failed_members() -> None:
    with session() as db:
        service = OperationCommandService(db)
        original_id = service.enqueue_source_catalog_refresh(
            catalog_plan(catalog_member("timeout"), catalog_member("payment")), trigger="cli"
        )
        members = {
            member.source_id: member
            for member in db.query(SourceCatalogRefreshMemberRecord).filter_by(
                operation_run_id=original_id
            )
        }
        members["timeout"].state = CatalogMemberState.FAILED.value
        members["timeout"].result_code = CatalogResultCode.TIMEOUT.value
        members["payment"].state = CatalogMemberState.BLOCKED.value
        members["payment"].result_code = CatalogResultCode.REQUIRES_PAYMENT.value
        operation = db.get(OperationRunRecord, original_id)
        assert operation is not None
        operation.status = "failed"
        db.commit()

        retry_id = service.retry_source_catalog_refresh(original_id, trigger="web")

        retry = db.get(OperationRunRecord, retry_id)
        assert retry is not None
        assert retry.requested_scope["retry_of_operation_id"] == original_id
        retry_members = (
            db.query(SourceCatalogRefreshMemberRecord).filter_by(operation_run_id=retry_id).all()
        )
        assert [member.source_id for member in retry_members] == ["timeout"]


def test_retry_catalog_refresh_rejects_an_empty_retry_plan() -> None:
    with session() as db:
        service = OperationCommandService(db)
        original_id = service.enqueue_source_catalog_refresh(
            catalog_plan(catalog_member("a")), trigger="cli"
        )
        operation = db.get(OperationRunRecord, original_id)
        assert operation is not None
        operation.status = "failed"
        db.commit()

        with pytest.raises(ValueError, match="catalog_refresh_retry_not_allowed"):
            service.retry_source_catalog_refresh(original_id, trigger="web")


def test_recover_abandoned_catalog_refresh_requires_explicit_confirmation() -> None:
    with session() as db:
        service = OperationCommandService(db)
        original_id = service.enqueue_source_catalog_refresh(
            catalog_plan(catalog_member("stuck"), catalog_member("finished")), trigger="cli"
        )
        members = {
            member.source_id: member
            for member in db.query(SourceCatalogRefreshMemberRecord).filter_by(
                operation_run_id=original_id
            )
        }
        members["stuck"].state = CatalogMemberState.RUNNING.value
        members["finished"].state = CatalogMemberState.SUCCEEDED.value
        db.get(OperationRunRecord, original_id).status = "partial"
        db.commit()

        with pytest.raises(ValueError, match="confirm_abandoned_required"):
            service.recover_abandoned_source_catalog_refresh(
                original_id, trigger="cli", confirm_abandoned=False
            )


def test_recover_abandoned_catalog_refresh_clones_only_confirmed_running_members() -> None:
    with session() as db:
        service = OperationCommandService(db)
        original_id = service.enqueue_source_catalog_refresh(
            catalog_plan(catalog_member("stuck"), catalog_member("finished")), trigger="cli"
        )
        members = {
            member.source_id: member
            for member in db.query(SourceCatalogRefreshMemberRecord).filter_by(
                operation_run_id=original_id
            )
        }
        members["stuck"].state = CatalogMemberState.RUNNING.value
        members["finished"].state = CatalogMemberState.SUCCEEDED.value
        db.get(OperationRunRecord, original_id).status = "partial"
        db.commit()

        recovery_id = service.recover_abandoned_source_catalog_refresh(
            original_id, trigger="cli", confirm_abandoned=True
        )

        recovery = db.get(OperationRunRecord, recovery_id)
        assert recovery is not None
        assert recovery.requested_scope["abandoned_recovery_of_operation_id"] == original_id
        assert [
            member.source_id
            for member in db.query(SourceCatalogRefreshMemberRecord).filter_by(
                operation_run_id=recovery_id
            )
        ] == ["stuck"]


def test_enqueue_fetch_records_complete_scope() -> None:
    with session() as db:
        operation_id = OperationCommandService(db).enqueue_fetch(
            source_id="github-openai-python",
            provider=None,
            dry_run=False,
            max_items=5,
            one_off=False,
            trigger="cli",
        )

        record = db.get(OperationRunRecord, operation_id)

        assert record is not None
        assert record.status == "queued"
        assert record.trigger == "cli"
        scope = dict(record.requested_scope)
        assert datetime.fromisoformat(scope.pop("deadline_at")).tzinfo is not None
        assert scope == {
            "source_id": "github-openai-python",
            "provider": None,
            "dry_run": False,
            "max_items": 5,
            "one_off": False,
            "trial": False,
        }


def test_retry_creates_new_auditable_operation() -> None:
    with session() as db:
        service = OperationCommandService(db)
        original_id = service.enqueue_fetch(source_id="github-openai-python", trigger="web")
        original = db.get(OperationRunRecord, original_id)
        assert original is not None
        original.status = "succeeded"
        db.commit()

        retry_id = service.retry(original_id, trigger="web")
        retry = db.get(OperationRunRecord, retry_id)

        assert retry is not None
        assert retry.id != original_id
        assert retry.trigger == "web"
        assert retry.requested_scope["retry_of_operation_id"] == original_id


def test_retry_rejects_durable_nonretryable_failure() -> None:
    with session() as db:
        original = OperationRunRecord(
            operation_type="event_recluster",
            trigger="web",
            status="failed",
            requested_scope={"event_id": 1, "actor": "web"},
            result_summary={},
            attempt_count=1,
            error_code="unsupported_action",
        )
        db.add(original)
        db.commit()

        with pytest.raises(ValueError, match="not retryable"):
            OperationCommandService(db).retry(original.id, trigger="web")


def test_enqueue_fetch_persists_operation_deadline() -> None:
    now = datetime(2026, 7, 12, 0, 0, tzinfo=UTC)
    with session() as db:
        service = OperationCommandService(
            db,
            settings=Settings(operation_timeout_seconds=30),
            utcnow=lambda: now,
        )

        operation_id = service.enqueue_fetch(source_id="source", trigger="cli")
        record = db.get(OperationRunRecord, operation_id)

        assert record is not None
        assert record.requested_scope["deadline_at"] == "2026-07-12T00:00:30+00:00"


def test_enqueue_event_pipeline_uses_window_versions_and_idempotency_key() -> None:
    now = datetime(2026, 7, 12, 0, 37, 12, tzinfo=UTC)
    with session() as db:
        operation_id = OperationCommandService(db, utcnow=lambda: now).enqueue_event_pipeline(
            window_hours=24, trigger="cli"
        )
        record = db.get(OperationRunRecord, operation_id)

        assert record is not None
        assert record.operation_type == "event_pipeline"
        assert record.requested_scope["window_hours"] == 24
        assert record.requested_scope["window_end"] == now.isoformat()
        versions = {
            "relevance": "relevance-v2",
            "newsworthiness": "newsworthiness-v2",
            "entities": "entities-v2",
            "cluster": "cluster-v2",
            "score": "score-v2",
        }
        assert record.requested_scope["algorithm_versions"] == versions
        expected_key = (
            "event-pipeline:"
            + sha256(
                dumps(
                    {
                        "window_end": now.isoformat(),
                        "window_hours": 24,
                        "versions": versions,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
        )
        assert record.requested_scope["idempotency_key"] == expected_key


def test_v2_pipeline_request_does_not_reuse_v1_hour_identity() -> None:
    now = datetime(2026, 7, 12, 0, 37, 12, tzinfo=UTC)
    bucket = now.replace(minute=0, second=0, microsecond=0)
    v1_versions = {
        "relevance": "relevance-v1",
        "entities": "entities-v1",
        "cluster": "cluster-v1",
    }
    old_key = (
        "event-pipeline:"
        + sha256(
            dumps(
                {
                    "window_end": bucket.isoformat(),
                    "window_hours": 24,
                    "versions": v1_versions,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
    )
    with session() as db:
        old = OperationRunRecord(
            operation_type="event_pipeline",
            trigger="cli",
            status="queued",
            requested_scope={
                "window_hours": 24,
                "algorithm_versions": v1_versions,
                "window_end": now.isoformat(),
                "idempotency_key": old_key,
            },
        )
        db.add(old)
        db.commit()

        new_id = OperationCommandService(db, utcnow=lambda: now).enqueue_event_pipeline(
            window_hours=24, trigger="cli"
        )
        new = db.get(OperationRunRecord, new_id)

        assert new is not None
        assert new.id != old.id
        assert new.requested_scope["algorithm_versions"] == {
            "relevance": "relevance-v2",
            "newsworthiness": "newsworthiness-v2",
            "entities": "entities-v2",
            "cluster": "cluster-v2",
            "score": "score-v2",
        }
        assert new.requested_scope["idempotency_key"] != old_key
