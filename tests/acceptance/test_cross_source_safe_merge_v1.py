"""PostgreSQL-only closure checks for cross-source safe event merging.

The database tests in this module require a dedicated test URL and create an
isolated, disposable schema.  They never fall back to the project's normal
``DATABASE_URL`` or settings loader.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Event, Lock
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from newsradar.db.models import (
    Base,
    DailyReportItemRecord,
    DailyReportRecord,
    EventCandidateRecord,
    EventItemRecord,
    EventMergeCandidateRecord,
    EventRecord,
    EventVersionRecord,
    OperationRunRecord,
    RawItemProcessingRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.event_merges.repository import EventMergeCandidateRepository
from newsradar.event_merges.schema import EventMergeFacts, MergeCandidateDraft
from newsradar.event_merges.service import EventMergeLeaseUnavailable, EventMergeService
from newsradar.events.repository import EventRepository

_RUN_POSTGRES_ENV = "NEWSRADAR_RUN_POSTGRES_ACCEPTANCE"
_TEST_POSTGRES_URL_ENV = "NEWSRADAR_TEST_POSTGRES_URL"
NOW = datetime(2026, 7, 16, 4, tzinfo=UTC)


def _explicit_test_postgres_url_or_skip() -> str:
    if os.getenv(_RUN_POSTGRES_ENV) != "1":
        pytest.skip(f"set {_RUN_POSTGRES_ENV}=1 to run isolated PostgreSQL acceptance")
    raw_url = os.getenv(_TEST_POSTGRES_URL_ENV)
    if not raw_url:
        pytest.skip(f"set dedicated {_TEST_POSTGRES_URL_ENV}; project DATABASE_URL is ignored")
    try:
        parsed = make_url(raw_url)
    except ArgumentError:
        pytest.skip(f"{_TEST_POSTGRES_URL_ENV} is not a valid database URL")
    database_name = parsed.database or ""
    if parsed.get_backend_name() != "postgresql" or "test" not in database_name.casefold():
        pytest.skip(
            f"{_TEST_POSTGRES_URL_ENV} must target a PostgreSQL database whose name contains test"
        )
    return raw_url


def test_postgres_acceptance_never_falls_back_to_project_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_RUN_POSTGRES_ENV, "1")
    monkeypatch.delenv(_TEST_POSTGRES_URL_ENV, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://ignored:ignored@invalid/project")

    with pytest.raises(pytest.skip.Exception, match=_TEST_POSTGRES_URL_ENV):
        _explicit_test_postgres_url_or_skip()


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    raw_url = _explicit_test_postgres_url_or_skip()
    schema_name = f"newsradar_merge_test_{uuid4().hex}"
    admin_engine = create_engine(
        raw_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )
    schema_created = False
    isolated_engine: Engine | None = None
    try:
        try:
            with admin_engine.begin() as connection:
                server_database = connection.scalar(select(func.current_database()))
                if not isinstance(server_database, str) or "test" not in server_database.casefold():
                    pytest.skip("configured PostgreSQL server database is not marked as a test")
                connection.execute(CreateSchema(schema_name))
                schema_created = True
        except SQLAlchemyError as error:
            pytest.skip(f"dedicated test PostgreSQL is unavailable: {error.__class__.__name__}")

        isolated_engine = create_engine(
            raw_url,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": 3,
                "options": f"-csearch_path={schema_name}",
            },
        )

        try:
            Base.metadata.create_all(isolated_engine)
            with isolated_engine.connect() as connection:
                assert connection.scalar(select(func.current_schema())) == schema_name
        except SQLAlchemyError as error:
            pytest.skip(
                f"isolated PostgreSQL schema could not be prepared: {error.__class__.__name__}"
            )
        yield isolated_engine
    finally:
        if isolated_engine is not None:
            isolated_engine.dispose()
        if schema_created:
            try:
                with admin_engine.begin() as connection:
                    connection.execute(DropSchema(schema_name, cascade=True))
            except SQLAlchemyError as error:
                pytest.fail(
                    f"isolated PostgreSQL test schema cleanup failed: {error.__class__.__name__}",
                    pytrace=False,
                )
        admin_engine.dispose()


@pytest.fixture
def postgres_session_factory(
    postgres_engine: Engine,
) -> Iterator[Callable[[], Session]]:
    yield lambda: Session(postgres_engine)
    table_names = ", ".join(
        postgres_engine.dialect.identifier_preparer.quote(table.name)
        for table in Base.metadata.tables.values()
    )
    with postgres_engine.begin() as connection:
        connection.exec_driver_sql(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE")


def _source(source_id: str) -> SourceDefinitionRecord:
    return SourceDefinitionRecord(
        id=source_id,
        name=source_id,
        provider_id="acceptance",
        nature="media",
        language="en",
        roles=["evidence"],
        topics=["ai"],
        authority_score=80,
        poll_interval_minutes=60,
        expected_fields=["title"],
        definition_hash=hashlib.sha256(source_id.encode()).hexdigest(),
    )


def _seed_event(
    session: Session,
    event_id: int,
    raw_item_id: int,
    *,
    url: str,
    title: str = "OpenAI launches Orion model",
) -> None:
    source_id = f"source-{event_id}"
    session.add_all(
        [
            _source(source_id),
            EventRecord(
                id=event_id,
                canonical_key=f"event-{event_id}",
                visibility="current",
                status="confirmed",
                occurred_at=NOW,
                current_version_number=1,
            ),
        ]
    )
    session.flush()
    session.add(
        RawItemRecord(
            id=raw_item_id,
            source_id=source_id,
            external_id=f"item-{raw_item_id}",
            canonical_url=f"https://aggregator.example/{raw_item_id}",
            original_url=url,
            payload={},
            title=title,
            summary=title,
            published_at=NOW,
        )
    )
    session.flush()
    session.add_all(
        [
            EventVersionRecord(event_id=event_id, version_number=1, payload={}),
            EventItemRecord(
                event_id=event_id,
                raw_item_id=raw_item_id,
                added_version_number=1,
            ),
            EventCandidateRecord(
                candidate_key=f"event-{event_id}",
                algorithm_version="cluster-v3",
                title=title,
                state="active",
                metadata_json={},
            ),
            RawItemProcessingRecord(
                raw_item_id=raw_item_id,
                stage="relevance",
                algorithm_version="relevance-v2",
                outcome="included",
                score=80,
                reason_codes=["ai_product_action"],
                details={},
            ),
        ]
    )


def _seed_operation(
    session: Session,
    operation_id: int,
    operation_type: str,
) -> None:
    session.add(
        OperationRunRecord(
            id=operation_id,
            operation_type=operation_type,
            trigger="test",
            status="running",
            requested_scope={},
            result_summary={},
        )
    )


def _seed_candidate(session: Session) -> EventMergeCandidateRecord:
    shared_url = "https://www.reuters.com/technology/orion-model"
    _seed_event(session, 1, 11, url=shared_url)
    _seed_event(session, 2, 22, url=shared_url)
    _seed_operation(session, 50, "event_merge_scan")
    _seed_operation(session, 51, "event_merge")
    _seed_operation(session, 52, "event_merge")
    session.commit()

    result = EventMergeService(session).scan(50, lambda _boundary: None)
    assert result.candidate_type_counts == {"deterministic_merge": 1}
    candidate = session.scalar(
        select(EventMergeCandidateRecord).where(
            EventMergeCandidateRecord.generated_operation_id == 50
        )
    )
    assert candidate is not None
    return candidate


def _seed_archived_report(session: Session) -> DailyReportItemRecord:
    report = DailyReportRecord(
        report_date=date(2026, 7, 16),
        timezone="Asia/Shanghai",
        window_hours=24,
        window_start=NOW,
        window_end=NOW,
        source_operation_id=50,
        status="archived",
        revision=1,
        generation_summary={"event_count": 1},
        generated_at=NOW,
        archived_at=NOW,
    )
    session.add(report)
    session.flush()
    item = DailyReportItemRecord(
        daily_report_id=report.id,
        event_id=1,
        event_version_number=1,
        section="confirmed",
        position=1,
        snapshot={"event_id": 1, "version_number": 1, "zh_title": "归档事件"},
    )
    session.add(item)
    session.commit()
    return item


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _state_hash(
    session: Session,
    *models: type[Base],
    excluded_columns: dict[type[Base], frozenset[str]] | None = None,
) -> str:
    payload: dict[str, list[list[object]]] = {}
    excluded = excluded_columns or {}
    for model in models:
        columns = tuple(
            column
            for column in model.__table__.columns
            if column.name not in excluded.get(model, frozenset())
        )
        primary_key = tuple(model.__table__.primary_key.columns)
        rows = session.execute(select(*columns).order_by(*primary_key)).all()
        payload[model.__tablename__] = [list(row) for row in rows]
    serialized = json.dumps(
        payload,
        default=_json_default,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


def _assert_no_event_leases(session: Session) -> None:
    assert (
        session.scalar(
            select(func.count())
            .select_from(EventRecord)
            .where(
                (EventRecord.lease_operation_id.is_not(None))
                | (EventRecord.lease_expires_at.is_not(None))
            )
        )
        == 0
    )


def _draft_from_record(
    record: EventMergeCandidateRecord,
    *,
    fingerprint: str | None = None,
) -> MergeCandidateDraft:
    return MergeCandidateDraft(
        left=EventMergeFacts.model_validate(record.facts_snapshot["left"]),
        right=EventMergeFacts.model_validate(record.facts_snapshot["right"]),
        candidate_type=record.candidate_type,
        algorithm_version=record.algorithm_version,
        input_fingerprint=fingerprint or record.input_fingerprint,
        reason_codes=tuple(record.reason_codes),
        zh_reason=record.zh_reason,
        zh_next_action=record.zh_next_action,
    )


def test_postgres_concurrent_apply_is_ordered_and_idempotent(
    postgres_session_factory: Callable[[], Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with postgres_session_factory() as setup:
        candidate_id = _seed_candidate(setup).id
        before_survivor_versions = setup.scalar(
            select(func.count())
            .select_from(EventVersionRecord)
            .where(EventVersionRecord.event_id == 1)
        )

    first_in_mutation = Event()
    release_first = Event()
    second_started_claim = Event()
    claims: list[tuple[int, int]] = []
    claims_lock = Lock()
    original_claim = EventRepository.claim_event
    original_publish = EventMergeService._publish_revalidated_pair

    def observed_claim(
        repository: EventRepository,
        event_id: int,
        operation_id: int,
        lease_until: datetime,
    ) -> bool:
        with claims_lock:
            claims.append((operation_id, event_id))
        if operation_id == 52 and event_id == 1:
            second_started_claim.set()
        return original_claim(repository, event_id, operation_id, lease_until)

    def hold_first_publication(service: EventMergeService, **kwargs):
        if kwargs["operation_id"] == 51:
            first_in_mutation.set()
            assert release_first.wait(timeout=10), "first apply was not released"
        return original_publish(service, **kwargs)

    monkeypatch.setattr(EventRepository, "claim_event", observed_claim)
    monkeypatch.setattr(
        EventMergeService,
        "_publish_revalidated_pair",
        hold_first_publication,
    )

    def apply(operation_id: int):
        with postgres_session_factory() as session:
            return EventMergeService(session).apply(
                candidate_id,
                operation_id,
                lambda _boundary: None,
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(apply, 51)
            assert first_in_mutation.wait(timeout=10), "first apply did not reach publication"
            second = pool.submit(apply, 52)
            assert second_started_claim.wait(timeout=10), "second apply did not contend"
            release_first.set()
            first_result = first.result(timeout=20)
            with pytest.raises(EventMergeLeaseUnavailable):
                second.result(timeout=20)
    finally:
        release_first.set()

    retry_result = apply(52)

    assert retry_result == first_result
    assert first_result.status == "succeeded"
    assert [event_id for operation_id, event_id in claims if operation_id == 51] == [1, 2]
    assert [event_id for operation_id, event_id in claims if operation_id == 52] == [1]
    with postgres_session_factory() as verify:
        assert (
            verify.scalar(
                select(func.count())
                .select_from(EventVersionRecord)
                .where(EventVersionRecord.event_id == 1)
            )
            == before_survivor_versions + 1
        )
        assert verify.get(EventMergeCandidateRecord, candidate_id).status == "applied"
        _assert_no_event_leases(verify)


def test_postgres_partial_root_unique_and_recheck_reuse_one_revision(
    postgres_session_factory: Callable[[], Session],
) -> None:
    with postgres_session_factory() as session:
        candidate = _seed_candidate(session)
        changed = _draft_from_record(candidate, fingerprint="b" * 64)
        repository = EventMergeCandidateRepository(session)

        assert repository.upsert_candidate(changed, 52).id == candidate.id
        duplicate_values = repository._candidate_values(
            changed,
            52,
            revision=99,
            supersedes_candidate_id=None,
        )
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.execute(
                    repository._insert(EventMergeCandidateRecord).values(duplicate_values)
                )
                session.flush()

        replacement = EventMergeService(session).review(candidate.id, "recheck", 51)
        retried = EventMergeService(session).review(candidate.id, "recheck", 51)

        assert replacement.id == retried.id
        assert replacement.revision == 2
        assert replacement.supersedes_candidate_id == candidate.id
        assert (
            session.scalar(
                select(func.count())
                .select_from(EventMergeCandidateRecord)
                .where(EventMergeCandidateRecord.supersedes_candidate_id.is_(None))
            )
            == 1
        )
        assert session.scalar(select(func.count()).select_from(EventMergeCandidateRecord)) == 2
        _assert_no_event_leases(session)


def test_postgres_stale_candidate_is_fenced_without_publication(
    postgres_session_factory: Callable[[], Session],
) -> None:
    with postgres_session_factory() as session:
        candidate = _seed_candidate(session)
        left = session.get(EventRecord, candidate.left_event_id)
        assert left is not None
        left.current_version_number = 2
        session.add(
            EventVersionRecord(
                event_id=left.id,
                version_number=2,
                payload={"reason": "acceptance-stale-version"},
            )
        )
        session.commit()
        before_version_count = session.scalar(select(func.count()).select_from(EventVersionRecord))

        result = EventMergeService(session).apply(candidate.id, 51, lambda _boundary: None)

        session.expire_all()
        assert result.status == "expired"
        assert result.error_code == "event_merge_version_changed"
        assert session.get(EventMergeCandidateRecord, candidate.id).status == "expired"
        assert (
            session.scalar(select(func.count()).select_from(EventVersionRecord))
            == before_version_count
        )
        _assert_no_event_leases(session)


def test_postgres_failed_second_publication_rolls_back_first(
    postgres_session_factory: Callable[[], Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with postgres_session_factory() as session:
        candidate = _seed_candidate(session)
        before = _state_hash(
            session,
            EventRecord,
            EventVersionRecord,
            EventItemRecord,
            EventMergeCandidateRecord,
            excluded_columns={
                EventRecord: frozenset({"lease_operation_id", "lease_expires_at", "updated_at"})
            },
        )

        original_publish = EventRepository.publish_complete_event
        publication_count = 0

        def fail_second(repository: EventRepository, *args, **kwargs):
            nonlocal publication_count
            publication_count += 1
            if publication_count == 2:
                raise RuntimeError("acceptance_second_publication_failure")
            return original_publish(repository, *args, **kwargs)

        monkeypatch.setattr(EventRepository, "publish_complete_event", fail_second)

        with pytest.raises(RuntimeError, match="acceptance_second_publication_failure"):
            EventMergeService(session).apply(candidate.id, 51, lambda _boundary: None)

        session.expire_all()
        assert publication_count == 2
        assert (
            _state_hash(
                session,
                EventRecord,
                EventVersionRecord,
                EventItemRecord,
                EventMergeCandidateRecord,
                excluded_columns={
                    EventRecord: frozenset({"lease_operation_id", "lease_expires_at", "updated_at"})
                },
            )
            == before
        )
        assert session.get(EventMergeCandidateRecord, candidate.id).status == "pending"
        _assert_no_event_leases(session)


def test_postgres_apply_preserves_archived_daily_report_bytes(
    postgres_session_factory: Callable[[], Session],
) -> None:
    with postgres_session_factory() as session:
        candidate = _seed_candidate(session)
        report_item = _seed_archived_report(session)
        before = _state_hash(session, DailyReportRecord, DailyReportItemRecord)
        original_version = session.scalar(
            select(EventVersionRecord).where(
                EventVersionRecord.event_id == 1,
                EventVersionRecord.version_number == 1,
            )
        )
        assert original_version is not None
        original_version_payload = json.dumps(
            original_version.payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

        result = EventMergeService(session).apply(candidate.id, 51, lambda _boundary: None)

        session.expire_all()
        assert result.status == "succeeded"
        assert _state_hash(session, DailyReportRecord, DailyReportItemRecord) == before
        assert (
            json.dumps(
                session.get(EventVersionRecord, original_version.id).payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            == original_version_payload
        )
        assert session.get(DailyReportItemRecord, report_item.id).snapshot == {
            "event_id": 1,
            "version_number": 1,
            "zh_title": "归档事件",
        }
        _assert_no_event_leases(session)


def test_postgres_scan_only_mutates_candidate_and_audit_state(
    postgres_session_factory: Callable[[], Session],
) -> None:
    with postgres_session_factory() as session:
        shared_url = "https://www.reuters.com/technology/orion-model"
        _seed_event(session, 1, 11, url=shared_url)
        _seed_event(session, 2, 22, url=shared_url)
        _seed_event(
            session,
            3,
            33,
            url="https://example.net/unrelated",
            title="Microsoft acquires Atlas project",
        )
        _seed_operation(session, 50, "event_merge_scan")
        session.commit()
        _seed_archived_report(session)
        protected = (
            EventRecord,
            EventVersionRecord,
            EventItemRecord,
            RawItemRecord,
            SourceDefinitionRecord,
            DailyReportRecord,
            DailyReportItemRecord,
        )
        before = _state_hash(session, *protected)

        result = EventMergeService(session).scan(50, lambda _boundary: None)

        session.expire_all()
        assert result.candidate_type_counts == {"deterministic_merge": 1}
        assert session.scalar(select(func.count()).select_from(EventMergeCandidateRecord)) == 1
        assert _state_hash(session, *protected) == before
        _assert_no_event_leases(session)
