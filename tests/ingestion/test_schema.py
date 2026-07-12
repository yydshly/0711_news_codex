from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from newsradar.ingestion.schema import FetchOutcome, FetchResult, NormalizedRawItem


def test_normalized_item_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        NormalizedRawItem(
            external_id="42",
            title="A",
            canonical_url="https://example.com/a",
            raw_payload={},
            invented=True,
        )


def test_fetch_result_is_immutable_and_retains_response_metadata() -> None:
    item = NormalizedRawItem(
        external_id="42",
        title="A",
        canonical_url="https://example.com/a",
        raw_payload={"origin": "feed"},
    )
    result = FetchResult(
        outcome=FetchOutcome.SUCCEEDED,
        items=(item,),
        http_status=200,
        final_url="https://example.com/feed",
        etag='"v1"',
        last_modified="Fri, 11 Jul 2026 00:00:00 GMT",
        next_cursor="next",
        items_received=1,
        warnings=("partial metadata",),
        rate_limit_remaining=9,
        rate_limit_reset=datetime(2026, 7, 11, 1, tzinfo=UTC),
        retry_after_seconds=30.0,
        completed_at=datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert result.items == (item,)
    assert result.next_cursor == "next"
    assert result.rate_limit_remaining == 9
    assert result.rate_limit_reset == datetime(2026, 7, 11, 1, tzinfo=UTC)
    assert result.retry_after_seconds == 30.0
    with pytest.raises(ValidationError):
        result.outcome = FetchOutcome.FAILED


def test_fetch_result_rejects_unknown_error_category() -> None:
    with pytest.raises(ValidationError):
        FetchResult(outcome=FetchOutcome.FAILED, error_category="not-a-category")


def test_fetch_result_rejects_negative_retry_metadata() -> None:
    with pytest.raises(ValidationError):
        FetchResult(outcome=FetchOutcome.FAILED, retry_after_seconds=-1)
