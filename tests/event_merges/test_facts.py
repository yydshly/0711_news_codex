from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    EventCandidateRecord,
    EventItemRecord,
    EventRecord,
    EventVersionRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.event_merges.facts import (
    EVENT_MERGE_RULE_VERSION,
    load_event_facts,
    merge_input_fingerprint,
    safe_url_identity,
    strong_url_identity,
)
from newsradar.event_merges.schema import EventMergeFacts


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
    engine.dispose()


def _seed_event(
    session: Session,
    *,
    canonical_url: str,
    original_url: str | None,
) -> int:
    source = SourceDefinitionRecord(
        id="source-1",
        name="Source One",
        provider_id="independent",
        nature="media",
        language="en",
        roles=["evidence"],
        topics=["ai"],
        authority_score=80,
        poll_interval_minutes=60,
        expected_fields=["title"],
        definition_hash="a" * 64,
    )
    raw = RawItemRecord(
        id=10,
        source_id=source.id,
        external_id="item-10",
        canonical_url=canonical_url,
        original_url=original_url,
        payload={},
        title="OpenAI launches Orion model with 128 parameters",
        summary="The Orion model was released today.",
        content="",
        publisher_name="Reuters",
        published_at=datetime(2026, 7, 16, 4, tzinfo=UTC),
    )
    event = EventRecord(
        id=1,
        canonical_key="event-1",
        visibility="current",
        status="confirmed",
        occurred_at=raw.published_at,
        current_version_number=1,
    )
    session.add_all(
        [
            source,
            raw,
            event,
            EventVersionRecord(
                event_id=event.id,
                version_number=1,
                payload={"evidence": [{"root_evidence_key": "publisher:reuters"}]},
            ),
            EventItemRecord(
                event_id=event.id,
                raw_item_id=raw.id,
                added_version_number=1,
            ),
            EventCandidateRecord(
                candidate_key=event.canonical_key,
                algorithm_version="cluster-v3",
                title=raw.title or "",
                state="active",
                metadata_json={},
            ),
        ]
    )
    session.commit()
    return event.id


def test_event_facts_exclude_google_news_intermediary_from_strong_identity(session) -> None:
    event_id = _seed_event(
        session,
        canonical_url="https://news.google.com/rss/articles/abc?token=secret",
        original_url="https://news.google.com/rss/articles/abc?token=secret",
    )

    facts = load_event_facts(session, event_id)

    assert facts.safe_url_identities == ("news.google.com/rss/articles/abc",)
    assert facts.strong_identities == ()
    assert facts.actions == ("launch",)
    assert "secret" not in repr(facts)


def test_event_facts_keep_real_original_media_identity(session) -> None:
    event_id = _seed_event(
        session,
        canonical_url="https://example.com/story?id=secret",
        original_url="https://www.reuters.com/technology/story-123",
    )

    facts = load_event_facts(session, event_id)

    assert "https://www.reuters.com/technology/story-123" in facts.strong_identities
    assert "example.com/story" not in facts.strong_identities
    assert "secret" not in repr(facts)


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/watch?v=AbCdEf123_-",
        "https://www.youtube.com/watch?v=AbCdEf123_-&feature=share",
        "https://youtu.be/AbCdEf123_-?si=tracking",
        "https://youtube.com/shorts/AbCdEf123_-?feature=share",
        "https://youtube.com/live/AbCdEf123_-?si=tracking",
        "https://youtube.com/embed/AbCdEf123_-?start=10",
    ],
)
def test_official_youtube_video_urls_share_one_strong_identity(url: str) -> None:
    assert strong_url_identity(url) == "youtube.com/watch/AbCdEf123_-"


def test_different_youtube_video_ids_have_different_strong_identities() -> None:
    first = strong_url_identity("https://www.youtube.com/watch?v=AbCdEf123_-")
    second = strong_url_identity("https://www.youtube.com/watch?v=ZyXwVu987_-")

    assert first == "youtube.com/watch/AbCdEf123_-"
    assert second == "youtube.com/watch/ZyXwVu987_-"
    assert first != second


@pytest.mark.parametrize("video_id", ["A", "AbCdEf123_", "AbCdEf123_-x"])
def test_youtube_video_id_must_be_exactly_eleven_safe_characters(
    video_id: str,
) -> None:
    assert strong_url_identity(f"https://youtube.com/watch?v={video_id}") is None


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/watch",
        "https://youtube.com/watch?v=AbCdEf123_-&v=ZyXwVu987_-",
        "https://youtube.com/watch?v=invalid.value",
        "https://youtube.com/watch?v=",
        "https://youtube.com:8443/watch?v=AbCdEf123_-",
        "https://youtube.example/watch?v=AbCdEf123_-",
        "https://example.com/watch?id=AbCdEf123_-",
        "https://example.com/story?token=SECRET-MARKER",
        "https://youtube.com/watch?v=AbCdEf123_-&" + "x=1&" * 32,
        "https://youtube.com/watch?v=AbCdEf123_-&q=" + "x" * 2050,
        "https://youtube.com/watch?v=AbCdEf123_-&broken",
        "https://youtube.com/watch?v=AbCdEf123_-&q=%FF",
        "https://youtube.com/watch?v=AbCdEf123_-#" + "x" * 4_100,
    ],
)
def test_query_bearing_or_ambiguous_urls_are_not_strong(url: str) -> None:
    identity = strong_url_identity(url)

    assert identity is None
    assert "SECRET-MARKER" not in repr(identity)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@example.com/story",
        "https://example.com/sto ry",
        "https://example.com/story\nnext",
        "https://example.com/story\x7fnext",
        "https://example.com\\story",
    ],
)
def test_url_identities_reject_userinfo_whitespace_controls_and_backslash(
    url: str,
) -> None:
    assert safe_url_identity(url) is None
    assert strong_url_identity(url) is None


def test_different_userinfo_urls_are_rejected_instead_of_colliding() -> None:
    urls = (
        "https://alice:first@example.com/story",
        "https://bob:second@example.com/story",
    )

    assert [safe_url_identity(url) for url in urls] == [None, None]
    assert [strong_url_identity(url) for url in urls] == [None, None]


def test_general_strong_identity_preserves_scheme() -> None:
    http = strong_url_identity("http://example.com/story")
    https = strong_url_identity("https://example.com/story")

    assert http == "http://example.com/story"
    assert https == "https://example.com/story"
    assert http != https
    assert safe_url_identity("http://example.com/story") == "example.com/story"
    assert safe_url_identity("https://example.com/story") == "example.com/story"


def test_ipv6_host_and_ipv6_with_port_do_not_collapse() -> None:
    host_only = "https://[2001:db8::1:8443]/story"
    host_with_port = "https://[2001:db8::1]:8443/story"

    assert safe_url_identity(host_only) == "[2001:db8::1:8443]/story"
    assert safe_url_identity(host_with_port) == "[2001:db8::1]:8443/story"
    assert strong_url_identity(host_only) == "https://[2001:db8::1:8443]/story"
    assert strong_url_identity(host_with_port) == "https://[2001:db8::1]:8443/story"
    assert strong_url_identity(host_only) != strong_url_identity(host_with_port)


def test_url_identities_reject_overlong_input_and_output_instead_of_truncating() -> None:
    overlong_inputs = (
        "https://example.com/" + "a" * 4_100,
        "https://example.com/" + "a" * 4_099 + "b",
    )
    long_outputs = (
        "https://example.com/" + "a" * 990 + "x",
        "https://example.com/" + "a" * 990 + "y",
    )

    for url in (*overlong_inputs, *long_outputs):
        assert safe_url_identity(url) is None
        assert strong_url_identity(url) is None


@pytest.mark.parametrize(
    "path",
    [
        "/token/SECRET-MARKER/story",
        "/api_key=SECRET-MARKER/story",
        "/credential:SECRET-MARKER/story",
        "/%2574oken/SECRET-MARKER/story",
        "/news%3Ftoken=SECRET-MARKER",
        "/news%253Ftoken=SECRET-MARKER",
        "/token;SECRET-MARKER/story",
        "/news%3Fapi_key=SECRET-MARKER",
    ],
)
def test_url_identities_reject_sensitive_plain_and_encoded_paths(path: str) -> None:
    url = f"https://example.com{path}"

    safe = safe_url_identity(url)
    strong = strong_url_identity(url)

    assert safe is None
    assert strong is None
    assert "SECRET-MARKER" not in repr((safe, strong))


def test_event_facts_never_persist_sensitive_path_marker(session) -> None:
    event_id = _seed_event(
        session,
        canonical_url="https://example.com/news%253Ftoken=SECRET-MARKER",
        original_url="https://example.com/news%3Fapi_key=SECRET-MARKER",
    )

    facts = load_event_facts(session, event_id)

    assert facts.safe_url_identities == ()
    assert facts.strong_identities == ()
    assert "SECRET-MARKER" not in repr(facts)


def test_merge_fingerprint_uses_current_v2_rule_version() -> None:
    left = EventMergeFacts(
        event_id=1,
        version_number=1,
        visibility="current",
        canonical_key="event-1",
        algorithm_versions=("cluster-v3",),
        raw_item_ids=(10,),
        source_ids=("source-1",),
        publishers=("Publisher",),
        published_at=(),
        safe_url_identities=(),
        strong_identities=(),
        object_entities=(),
        actions=(),
        evidence_roots=(),
    )
    right = left.model_copy(update={"event_id": 2, "canonical_key": "event-2"})

    assert EVENT_MERGE_RULE_VERSION == "event-merge-v2"
    assert merge_input_fingerprint(left, right) != merge_input_fingerprint(
        left.model_copy(update={"canonical_key": "legacy-event-1"}), right
    )


def test_event_facts_sort_and_deduplicate_active_membership(session) -> None:
    event_id = _seed_event(
        session,
        canonical_url="https://example.com/story",
        original_url="https://www.reuters.com/story",
    )
    session.add(
        EventItemRecord(
            event_id=event_id,
            raw_item_id=10,
            added_version_number=0,
        )
    )
    session.commit()

    facts = load_event_facts(session, event_id)

    assert facts.raw_item_ids == (10,)


@pytest.mark.parametrize(
    "url",
    [
        "https://news.google.com:443/rss/articles/abc",
        "https://news.google.com:8443/rss/articles/abc",
        "https://news.yahoo.com:443/story/abc",
        "https://news.yahoo.com:8443/story/abc",
    ],
)
def test_intermediary_host_with_any_explicit_port_is_never_strong(url: str) -> None:
    assert strong_url_identity(url) is None
