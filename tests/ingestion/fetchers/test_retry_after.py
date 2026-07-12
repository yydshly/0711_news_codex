from __future__ import annotations

from datetime import UTC, datetime

import httpx

from newsradar.ingestion.fetchers.base import response_result
from newsradar.ingestion.fetchers.retry_after import parse_retry_after


def test_retry_after_accepts_delta_seconds() -> None:
    assert parse_retry_after("12") == 12.0
    assert parse_retry_after("-1") == 0.0


def test_retry_after_accepts_http_date_and_rejects_invalid_value() -> None:
    now = datetime(2026, 7, 12, tzinfo=UTC)

    assert parse_retry_after("Sun, 12 Jul 2026 00:02:00 GMT", now=now) == 120.0
    assert parse_retry_after("invalid", now=now) is None


def test_fetch_result_carries_retry_after_hint() -> None:
    response = httpx.Response(
        429,
        headers={"Retry-After": "12"},
        request=httpx.Request("GET", "https://api.example.test/items"),
    )

    result = response_result(response)

    assert result.retry_after_seconds == 12.0
