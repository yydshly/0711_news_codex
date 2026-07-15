from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    OperationRunRecord,
    SourceCatalogRefreshMemberRecord,
    SourceDefinitionRecord,
)
from newsradar.web.source_wave_queries import SourceWaveQueryService


def _source(source_id: str) -> SourceDefinitionRecord:
    return SourceDefinitionRecord(
        id=source_id,
        name=source_id,
        provider_id="test",
        target_type="publisher_feed",
        availability="ready",
        coverage_mode="direct",
        status="candidate",
        nature="first_party",
        language="en",
        roles=[],
        topics=[],
        authority_score=1,
        poll_interval_minutes=60,
        expected_fields=[],
        notes="test",
        definition_hash="b" * 64,
    )


def _operation(kind: str, created_at: datetime) -> OperationRunRecord:
    return OperationRunRecord(
        operation_type=kind,
        trigger="test",
        status="succeeded",
        requested_scope={"catalog_digest": "frozen-digest"},
        result_summary={},
        created_at=created_at,
    )


def _member(
    operation_id: int, source_id: str, **values: str | None
) -> SourceCatalogRefreshMemberRecord:
    return SourceCatalogRefreshMemberRecord(
        operation_run_id=operation_id,
        source_id=source_id,
        provider_id=values.get("provider_id") or "reddit",
        definition_hash="a" * 64,
        availability_snapshot=values.get("availability") or "ready",
        coverage_mode_snapshot=values.get("coverage_mode") or "direct",
        access_kind_snapshot="rss",
        lane=values.get("lane") or "content",
        state=values.get("state") or "succeeded",
        result_code=values.get("result_code"),
        conclusion="测试结论",
        content_probe_run_ids=[],
        attempt_count=1,
    )


def test_list_waves_only_includes_newest_catalog_refresh_operations() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
        older = _operation("source_catalog_refresh", now - timedelta(minutes=1))
        newer = _operation("source_catalog_refresh", now)
        session.add_all((older, newer, _operation("fetch", now + timedelta(minutes=1))))
        session.commit()

        waves = SourceWaveQueryService(session).list_waves()

    assert [wave.operation_id for wave in waves] == [newer.id, older.id]


def test_detail_filters_members_paginates_and_counts_mutually_exclusive_outcomes() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        operation = _operation("source_catalog_refresh", datetime.now(UTC))
        session.add(operation)
        session.add_all(_source(source_id) for source_id in ("a", "b", "c", "d", "e", "f"))
        session.flush()
        session.add_all(
            (
                _member(operation.id, "a"),
                _member(operation.id, "b", lane="capability", state="succeeded"),
                _member(operation.id, "c", lane="catalog", state="succeeded"),
                _member(operation.id, "d", lane="content", state="degraded"),
                _member(
                    operation.id,
                    "e",
                    lane="capability",
                    state="failed",
                    result_code="missing_credentials",
                ),
                _member(
                    operation.id,
                    "f",
                    lane="capability",
                    state="blocked",
                    result_code="missing_credentials",
                ),
            )
        )
        session.commit()

        detail = SourceWaveQueryService(session).detail(
            operation.id,
            lane="capability",
            provider_id="reddit",
            state="blocked",
            result_code="missing_credentials",
            page=1,
            page_size=1,
        )
        all_members = SourceWaveQueryService(session).detail(operation.id, page=2, page_size=2)

    assert detail is not None
    assert detail.total == 1
    assert [row.source_id for row in detail.members] == ["f"]
    assert detail.summary.content_success == 1
    assert detail.summary.capability_confirmed == 1
    assert detail.summary.catalog_confirmed == 1
    assert detail.summary.degraded == 1
    assert detail.summary.runtime_failed == 2
    assert sum(detail.summary.counts) == 6
    assert all_members is not None
    assert [row.source_id for row in all_members.members] == ["c", "d"]


def test_detail_rejects_missing_or_non_catalog_operation() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        other = _operation("fetch", datetime.now(UTC))
        session.add(other)
        session.commit()

        assert SourceWaveQueryService(session).detail(999) is None
        assert SourceWaveQueryService(session).detail(other.id) is None
