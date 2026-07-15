import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newsradar.db.models import Base, OperationRunRecord, SourceCatalogRefreshMemberRecord
from newsradar.sources.catalog_refresh import (
    CatalogMemberState,
    CatalogRefreshLane,
    CatalogRefreshMemberSnapshot,
    CatalogRefreshPlan,
    CatalogResultCode,
)
from newsradar.sources.catalog_refresh_repository import CatalogRefreshRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def plan(*members: CatalogRefreshMemberSnapshot) -> CatalogRefreshPlan:
    return CatalogRefreshPlan.from_members(members)


def member(source_id: str, *, lane: CatalogRefreshLane = CatalogRefreshLane.CONTENT):
    return CatalogRefreshMemberSnapshot(
        source_id=source_id,
        provider_id="provider",
        definition_hash=f"hash-{source_id}",
        availability="ready",
        coverage_mode="direct",
        access_kind="rss",
        lane=lane,
    )


def test_create_members_freezes_plan_without_reading_live_source_definitions(
    session: Session,
) -> None:
    repository = CatalogRefreshRepository(session)
    repository.create_members(11, plan(member("z"), member("a")))

    records = repository.unfinished_members(11)

    assert [record.source_id for record in records] == ["a", "z"]
    assert records[0].definition_hash == "hash-a"
    assert records[0].state == CatalogMemberState.PENDING.value
    assert records[0].attempt_count == 0


def test_create_members_persists_new_provider_definition_hash(session: Session) -> None:
    snapshot = CatalogRefreshMemberSnapshot(
        source_id="provider-hash",
        provider_id="provider",
        definition_hash="source-definition-hash",
        provider_definition_hash="provider-definition-hash",
        availability="ready",
        coverage_mode="direct",
        access_kind="rss",
        lane=CatalogRefreshLane.CONTENT,
    )

    CatalogRefreshRepository(session).create_members(11, plan(snapshot))

    stored = session.scalar(select(SourceCatalogRefreshMemberRecord))
    assert stored is not None
    assert stored.provider_definition_hash == "provider-definition-hash"


def test_unique_operation_source_constraint_rejects_duplicate_member(session: Session) -> None:
    repository = CatalogRefreshRepository(session)
    repository.create_members(11, plan(member("a")))
    session.add(
        SourceCatalogRefreshMemberRecord(
            operation_run_id=11,
            source_id="a",
            provider_id="provider",
            definition_hash="different",
            availability_snapshot="ready",
            coverage_mode_snapshot="direct",
            access_kind_snapshot="rss",
            lane="content",
            state="pending",
            content_probe_run_ids=[],
            attempt_count=0,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_start_finish_and_unfinished_members_exclude_terminal_records(session: Session) -> None:
    repository = CatalogRefreshRepository(session)
    repository.create_members(11, plan(member("a"), member("b")))

    started = repository.start_member(11, "a")
    finished = repository.finish_member(
        11,
        "a",
        state=CatalogMemberState.SUCCEEDED,
        result_code=None,
        conclusion="已完成",
        content_probe_run_ids=[3],
    )

    assert started.attempt_count == 1
    assert started.started_at is not None
    assert finished.finished_at is not None
    assert [record.source_id for record in repository.unfinished_members(11)] == ["b"]


def test_finishing_a_member_advances_operation_progress_once(session: Session) -> None:
    session.add(
        OperationRunRecord(
            id=11,
            operation_type="source_catalog_refresh",
            trigger="test",
            status="running",
            requested_scope={},
            result_summary={},
            progress_current=0,
            progress_total=2,
            attempt_count=1,
        )
    )
    session.commit()
    repository = CatalogRefreshRepository(session)
    repository.create_members(11, plan(member("a"), member("b")))
    repository.finish_member(11, "a", CatalogMemberState.SUCCEEDED, None, "完成")
    repository.finish_member(11, "a", CatalogMemberState.SUCCEEDED, None, "重复完成")

    assert session.get(OperationRunRecord, 11).progress_current == 1


def test_start_missing_member_raises_lookup_error(session: Session) -> None:
    with pytest.raises(LookupError):
        CatalogRefreshRepository(session).start_member(11, "missing")


def test_summary_and_retryable_plan_use_only_retryable_failure_snapshots(session: Session) -> None:
    repository = CatalogRefreshRepository(session)
    repository.create_members(11, plan(member("timeout"), member("no-content")))
    repository.start_member(11, "timeout")
    repository.finish_member(
        11, "timeout", CatalogMemberState.FAILED, CatalogResultCode.TIMEOUT, "超时"
    )
    repository.start_member(11, "no-content")
    repository.finish_member(
        11, "no-content", CatalogMemberState.DEGRADED, CatalogResultCode.NO_CONTENT, "无内容"
    )

    assert repository.summary(11) == {"content_degraded": 1, "content_failed": 1}
    retry = repository.retryable_plan(11)
    assert [snapshot.source_id for snapshot in retry.members] == ["timeout"]
    assert retry.catalog_digest
    persisted = session.scalar(
        select(SourceCatalogRefreshMemberRecord).where(
            SourceCatalogRefreshMemberRecord.source_id == "timeout"
        )
    )
    assert persisted is not None
    assert repository.snapshot_from_record(persisted).definition_hash == "hash-timeout"


def test_finish_missing_member_raises_lookup_error(session: Session) -> None:
    with pytest.raises(LookupError):
        CatalogRefreshRepository(session).finish_member(
            11, "missing", CatalogMemberState.FAILED, CatalogResultCode.TIMEOUT, "超时"
        )
