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
        completed_at=datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert result.items == (item,)
    assert result.next_cursor == "next"
    with pytest.raises(ValidationError):
        result.outcome = FetchOutcome.FAILED
