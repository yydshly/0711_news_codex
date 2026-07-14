from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    DuplicateCandidateRecord,
    FetchRunRecord,
    RawItemRecord,
    RawItemSnapshotRecord,
    SourceDefinitionRecord,
)
from newsradar.web.item_queries import ItemQueryService

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


def _source(source_id: str, *, provider_id: str, language: str = "en") -> SourceDefinitionRecord:
    return SourceDefinitionRecord(
        id=source_id,
        name=source_id.title(),
        provider_id=provider_id,
        target_type="publisher_feed",
        availability="ready",
        coverage_mode="direct",
        status="active",
        nature="professional_media",
        language=language,
        roles=["discovery", "evidence"],
        topics=["ai"],
        authority_score=80,
        poll_interval_minutes=60,
        expected_fields=["title"],
        definition_hash=f"{source_id}-hash",
    )


def _item(
    source_id: str,
    external_id: str,
    *,
    title: str,
    published_at: datetime | None,
    first_seen_at: datetime,
    language: str = "en",
) -> RawItemRecord:
    return RawItemRecord(
        source_id=source_id,
        external_id=external_id,
        canonical_url=f"https://example.test/{source_id}/{external_id}",
        canonical_url_hash=f"url-{source_id}-{external_id}",
        payload={"secret": "list-query-must-not-load-this"},
        title=title,
        language=language,
        published_at=published_at,
        first_seen_at=first_seen_at,
        last_seen_at=first_seen_at,
    )


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add_all(
        [_source("reuters-ai", provider_id="reuters"), _source("hn-ai", provider_id="hn")]
    )
    session.flush()
    return session


def test_list_items_uses_database_order_filters_and_never_selects_payload() -> None:
    session = _session()
    try:
        newest = _item(
            "reuters-ai", "newest", title="AI Launch", published_at=NOW,
            first_seen_at=NOW - timedelta(minutes=2),
        )
        older = _item(
            "reuters-ai", "older", title="AI Policy", published_at=NOW - timedelta(days=1),
            first_seen_at=NOW - timedelta(minutes=1),
        )
        no_date = _item(
            "hn-ai", "nodate", title="AI Discussion", published_at=None,
            first_seen_at=NOW,
        )
        session.add_all([newest, older, no_date])
        session.flush()
        newest_id, older_id = newest.id, older.id
        session.add(DuplicateCandidateRecord(
            raw_item_id=newest.id, candidate_raw_item_id=older.id, match_type="title", score=0.95,
        ))
        session.commit()

        statements: list[str] = []
        event.listen(
            session.bind,
            "before_cursor_execute",
            lambda *args: statements.append(args[2]),
        )
        page = ItemQueryService(session).list_items(
            limit=10, provider_id="reuters", language="en", title_query="AI"
        )

        assert page.total == 2
        assert [row.raw_item_id for row in page.rows] == [newest_id, older_id]
        assert page.rows[0].duplicate_count == 1
        assert page.rows[0].evidence_roles == ("discovery", "evidence")
        assert all("payload" not in statement.lower() for statement in statements)
    finally:
        session.close()


def test_list_items_handles_a_page_beyond_ten_thousand_records() -> None:
    session = _session()
    try:
        session.add_all(
            _item(
                "reuters-ai", str(index), title=f"AI {index}", published_at=NOW,
                first_seen_at=NOW + timedelta(seconds=index),
            )
            for index in range(10_001)
        )
        session.commit()

        page = ItemQueryService(session).list_items(limit=1, offset=10_000)

        assert page.total == 10_001
        assert len(page.rows) == 1
        assert page.rows[0].title == "AI 0"
    finally:
        session.close()


def test_list_items_filters_by_source_published_and_first_seen_ranges() -> None:
    session = _session()
    try:
        included = _item(
            "reuters-ai",
            "included",
            title="Included",
            published_at=NOW - timedelta(hours=2),
            first_seen_at=NOW - timedelta(hours=1),
        )
        session.add_all(
            [
                included,
                _item(
                    "reuters-ai",
                    "too-old",
                    title="Too old",
                    published_at=NOW - timedelta(days=2),
                    first_seen_at=NOW - timedelta(hours=1),
                ),
                _item(
                    "hn-ai",
                    "wrong-source",
                    title="Wrong source",
                    published_at=NOW - timedelta(hours=2),
                    first_seen_at=NOW - timedelta(hours=1),
                ),
            ]
        )
        session.commit()

        page = ItemQueryService(session).list_items(
            source_id="reuters-ai",
            published_after=NOW - timedelta(hours=3),
            first_seen_after=NOW - timedelta(hours=2),
        )

        assert [row.title for row in page.rows] == ["Included"]
    finally:
        session.close()


def test_item_detail_loads_payload_versions_and_duplicate_candidates_only_on_demand() -> None:
    session = _session()
    try:
        first = _item("reuters-ai", "one", title="First", published_at=NOW, first_seen_at=NOW)
        first.authors = ["Reporter One"]
        first.summary = "A concise summary"
        first.discussion_url = "https://discussion.example.test/one"
        first.engagement = {"score": 88, "comments": 21}
        first.publisher_name = "Example Publisher"
        first.origin_resolution_status = "resolved"
        second = _item("hn-ai", "two", title="Second", published_at=NOW, first_seen_at=NOW)
        session.add_all([first, second])
        session.flush()
        session.add_all([
            RawItemSnapshotRecord(
                raw_item_id=first.id, content_hash="v1", snapshot={"title": "old"}
            ),
            RawItemSnapshotRecord(
                raw_item_id=first.id, content_hash="v2", snapshot={"title": "new"}
            ),
            DuplicateCandidateRecord(
                raw_item_id=first.id,
                candidate_raw_item_id=second.id,
                match_type="canonical_url",
                score=1.0,
            ),
        ])
        session.commit()

        detail = ItemQueryService(session).get_item(first.id)
        duplicates = ItemQueryService(session).list_duplicate_candidates()

        assert detail is not None
        assert detail.payload["secret"] == "list-query-must-not-load-this"
        assert detail.authors == ("Reporter One",)
        assert detail.summary == "A concise summary"
        assert detail.discussion_url == "https://discussion.example.test/one"
        assert detail.engagement == {"score": 88, "comments": 21}
        assert detail.publisher_name == "Example Publisher"
        assert detail.origin_resolution_status == "resolved"
        assert [version.content_hash for version in detail.versions] == ["v2", "v1"]
        assert duplicates[0].left_item_id == first.id
        assert duplicates[0].right_item_id == second.id
    finally:
        session.close()


def test_list_fetch_runs_orders_newest_and_scopes_to_source() -> None:
    session = _session()
    try:
        session.add_all([
            FetchRunRecord(source_id="reuters-ai", outcome="succeeded", started_at=NOW,
                           items_received=3, items_inserted=2),
            FetchRunRecord(
                source_id="hn-ai",
                outcome="failed",
                started_at=NOW + timedelta(minutes=1),
                error_code="timeout",
                error_message="timed out",
            ),
        ])
        session.commit()

        rows = ItemQueryService(session).list_fetch_runs(source_id="reuters-ai")

        assert len(rows) == 1
        assert rows[0].source_id == "reuters-ai"
        assert rows[0].items_inserted == 2
    finally:
        session.close()
