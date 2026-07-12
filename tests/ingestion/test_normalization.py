from __future__ import annotations

from datetime import UTC, datetime, timedelta

from newsradar.ingestion.normalization import (
    content_hash,
    normalize_title,
    normalize_url,
    title_similarity,
)
from newsradar.ingestion.schema import NormalizedRawItem


def item(**changes: object) -> NormalizedRawItem:
    data = {
        "external_id": "42",
        "title": "Release 2.0",
        "canonical_url": "https://example.com/releases/2",
        "authors": ("News Radar",),
        "summary": "Summary",
        "content": "Body",
        "published_at": datetime(2026, 7, 11, tzinfo=UTC),
        "source_updated_at": datetime(2026, 7, 11, 1, tzinfo=UTC),
        "engagement": {"likes": 1},
        "raw_payload": {"volatile": "value"},
    }
    data.update(changes)
    return NormalizedRawItem(**data)


def test_normalize_url_removes_fragment_default_port_and_tracking_only() -> None:
    assert normalize_url(
        "HTTPS://Example.COM:443/path?utm_source=mail&b=2&fbclid=abc&a=1#section"
    ) == "https://example.com/path?a=1&b=2"


def test_normalize_url_preserves_business_parameters() -> None:
    assert normalize_url("https://example.com/search?query=ai&page=2&utm_campaign=weekly") == (
        "https://example.com/search?page=2&query=ai"
    )


def test_normalize_title_decodes_entities_normalizes_unicode_and_collapses_space() -> None:
    value = "  Release&nbsp;\uff12.\uff10 &amp;\n updates  "
    assert normalize_title(value) == "Release 2.0 & updates"


def test_content_hash_is_stable_and_excludes_engagement_and_raw_payload() -> None:
    original = item()
    observation_update = item(engagement={"likes": 99}, raw_payload={"other": "payload"})

    assert content_hash(original) == content_hash(observation_update)
    expected = "8056597a71c701609e9d589f6538ae163f75d3da2a4ce4370d29c1ed7a3465e9"
    assert content_hash(original) == expected


def test_title_similarity_uses_normalized_tokens_and_seven_day_boundary() -> None:
    original = item(
        title="Release 2.0! | NewsRadar",
        published_at=datetime(2026, 7, 11, tzinfo=UTC),
    )
    at_boundary = item(
        title="release 2.0",
        published_at=datetime(2026, 7, 18, tzinfo=UTC),
    )
    outside_boundary = item(
        title="release 2.0",
        published_at=datetime(2026, 7, 18, tzinfo=UTC) + timedelta(microseconds=1),
    )

    assert title_similarity(original, at_boundary) == 1.0
    assert title_similarity(original, outside_boundary) == 0.0
