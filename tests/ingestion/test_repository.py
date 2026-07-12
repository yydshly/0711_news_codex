from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    DuplicateCandidateRecord,
    FetchRunItemRecord,
    FetchRunRecord,
    RawItemRecord,
    RawItemSnapshotRecord,
    SourceDefinitionRecord,
)
from newsradar.ingestion.repository import ItemAction, RawItemRepository
from newsradar.ingestion.schema import NormalizedRawItem


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def item(**changes: object) -> NormalizedRawItem:
    data = {
        "external_id": "42",
        "title": "Release 2.0",
        "canonical_url": "https://example.com/releases/2?utm_source=feed",
        "authors": ("News Radar",),
        "summary": "Summary",
        "content": "Body",
        "published_at": datetime(2026, 7, 11, tzinfo=UTC),
        "source_updated_at": datetime(2026, 7, 11, 1, tzinfo=UTC),
        "engagement": {"likes": 1},
        "raw_payload": {"provider": "example"},
    }
    data.update(changes)
    return NormalizedRawItem(**data)


def prepare(session: Session) -> int:
    session.add(
        SourceDefinitionRecord(
            id="source",
            name="Source",
            nature="official",
            language="en",
            roles=[],
            topics=[],
            authority_score=1,
            poll_interval_minutes=60,
            expected_fields=[],
            definition_hash="0" * 64,
        )
    )
    session.flush()
    fetch_run = FetchRunRecord(source_id="source")
    session.add(fetch_run)
    session.flush()
    return fetch_run.id


def test_upsert_inserts_item_initial_snapshot_and_run_audit() -> None:
    with make_session() as session:
        fetch_run_id = prepare(session)
        result = RawItemRepository(session).upsert(fetch_run_id, "source", item())

        assert result.action is ItemAction.INSERTED
        assert result.raw_item_id is not None
        assert session.scalar(select(func.count()).select_from(RawItemRecord)) == 1
        assert session.scalar(select(func.count()).select_from(RawItemSnapshotRecord)) == 1
        audit = session.scalar(select(FetchRunItemRecord))
        assert audit is not None
        assert audit.raw_item_id == result.raw_item_id
        assert audit.action == ItemAction.INSERTED.value


def test_upsert_marks_same_content_as_unchanged_without_another_snapshot() -> None:
    with make_session() as session:
        fetch_run_id = prepare(session)
        repository = RawItemRepository(session)
        first = repository.upsert(fetch_run_id, "source", item())
        result = repository.upsert(fetch_run_id, "source", item())

        assert result == result.__class__(first.raw_item_id, ItemAction.UNCHANGED)
        assert session.scalar(select(func.count()).select_from(RawItemSnapshotRecord)) == 1


def test_upsert_updates_changed_content_and_creates_one_new_snapshot() -> None:
    with make_session() as session:
        fetch_run_id = prepare(session)
        repository = RawItemRepository(session)
        first = repository.upsert(fetch_run_id, "source", item())
        result = repository.upsert(fetch_run_id, "source", item(content="Changed body"))

        assert result == result.__class__(first.raw_item_id, ItemAction.UPDATED)
        assert session.scalar(select(func.count()).select_from(RawItemSnapshotRecord)) == 2
        assert session.get(RawItemRecord, first.raw_item_id).content == "Changed body"  # type: ignore[union-attr]


def test_upsert_updates_engagement_without_a_content_snapshot() -> None:
    with make_session() as session:
        fetch_run_id = prepare(session)
        repository = RawItemRepository(session)
        first = repository.upsert(fetch_run_id, "source", item())
        result = repository.upsert(fetch_run_id, "source", item(engagement={"likes": 99}))

        assert result == result.__class__(first.raw_item_id, ItemAction.UNCHANGED)
        assert session.scalar(select(func.count()).select_from(RawItemSnapshotRecord)) == 1
        assert session.get(RawItemRecord, first.raw_item_id).engagement == {"likes": 99}  # type: ignore[union-attr]


def test_upsert_uses_same_source_canonical_url_when_external_id_changes() -> None:
    with make_session() as session:
        fetch_run_id = prepare(session)
        repository = RawItemRepository(session)
        first = repository.upsert(fetch_run_id, "source", item())
        result = repository.upsert(fetch_run_id, "source", item(external_id="changed-id"))

        assert result == result.__class__(first.raw_item_id, ItemAction.UNCHANGED)
        assert session.scalar(select(func.count()).select_from(RawItemRecord)) == 1


def test_external_id_and_canonical_url_conflict_is_skipped_without_merging() -> None:
    with make_session() as session:
        fetch_run_id = prepare(session)
        repository = RawItemRepository(session)
        first = repository.upsert(fetch_run_id, "source", item())
        second = repository.upsert(
            fetch_run_id,
            "source",
            item(external_id="43", canonical_url="https://example.com/releases/3"),
        )
        conflict = repository.upsert(
            fetch_run_id,
            "source",
            item(external_id="42", canonical_url="https://example.com/releases/3"),
        )

        assert conflict == conflict.__class__(None, ItemAction.SKIPPED, "identity_conflict")
        assert session.scalar(select(func.count()).select_from(RawItemRecord)) == 2
        assert session.get(RawItemRecord, first.raw_item_id).external_id == "42"  # type: ignore[union-attr]
        assert session.get(RawItemRecord, second.raw_item_id).external_id == "43"  # type: ignore[union-attr]


def test_canonical_match_across_sources_creates_idempotent_duplicate_candidate() -> None:
    with make_session() as session:
        fetch_run_id = prepare(session)
        repository = RawItemRepository(session)
        first = repository.upsert(fetch_run_id, "source", item())
        session.add(
            SourceDefinitionRecord(
                id="other",
                name="Other",
                nature="official",
                language="en",
                roles=[],
                topics=[],
                authority_score=1,
                poll_interval_minutes=60,
                expected_fields=[],
                definition_hash="1" * 64,
            )
        )
        other_run = FetchRunRecord(source_id="other")
        session.add(other_run)
        session.flush()
        second = repository.upsert(other_run.id, "other", item(external_id="other-42"))
        repository.upsert(other_run.id, "other", item(external_id="other-42"))

        assert second.action is ItemAction.INSERTED
        candidate = session.scalar(select(DuplicateCandidateRecord))
        assert candidate is not None
        assert {candidate.raw_item_id, candidate.candidate_raw_item_id} == {
            first.raw_item_id,
            second.raw_item_id,
        }
        assert candidate.match_type == "canonical_url"
        assert (
            session.scalar(
                select(func.count())
                .select_from(DuplicateCandidateRecord)
                .where(DuplicateCandidateRecord.match_type == "canonical_url")
            )
            == 1
        )


def test_title_candidate_is_idempotent() -> None:
    with make_session() as session:
        fetch_run_id = prepare(session)
        repository = RawItemRepository(session)
        first = repository.upsert(fetch_run_id, "source", item())
        second = repository.upsert(
            fetch_run_id,
            "source",
            item(external_id="43", canonical_url="https://example.com/releases/other"),
        )
        repository.upsert(
            fetch_run_id,
            "source",
            item(external_id="43", canonical_url="https://example.com/releases/other"),
        )

        candidate = session.scalar(select(DuplicateCandidateRecord))
        assert candidate is not None
        assert {candidate.raw_item_id, candidate.candidate_raw_item_id} == {
            first.raw_item_id,
            second.raw_item_id,
        }
        assert candidate.match_type == "title"
        assert candidate.score == 1.0
        assert session.scalar(select(func.count()).select_from(DuplicateCandidateRecord)) == 1


def test_failure_rolls_back_only_that_item_and_later_items_remain_processable() -> None:
    with make_session() as session:
        fetch_run_id = prepare(session)
        repository = RawItemRepository(session)
        first = repository.upsert(fetch_run_id, "source", item())
        failed = repository.record_failure(
            fetch_run_id, "source", item(external_id="bad"), "parse_error"
        )
        later = repository.upsert(
            fetch_run_id,
            "source",
            item(
                external_id="later",
                canonical_url="https://example.com/later",
                title="Later release",
                published_at=datetime(2026, 7, 11, tzinfo=UTC) + timedelta(days=30),
            ),
        )
        session.commit()

        assert first.action is ItemAction.INSERTED
        assert failed == failed.__class__(None, ItemAction.FAILED, "parse_error")
        assert later.action is ItemAction.INSERTED
        assert session.scalar(select(func.count()).select_from(RawItemRecord)) == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(FetchRunItemRecord)
                .where(FetchRunItemRecord.action == "failed")
            )
            == 1
        )
