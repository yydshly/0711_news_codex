from __future__ import annotations

from datetime import UTC, datetime

import pytest

from newsradar.operations.deadlines import OperationDeadline, OperationTimedOut


def test_operation_deadline_rejects_expired_scope() -> None:
    deadline = OperationDeadline.from_scope(
        {"deadline_at": "2026-07-12T00:00:00+00:00"},
        now=lambda: datetime(2026, 7, 12, 0, 0, 1, tzinfo=UTC),
    )

    with pytest.raises(OperationTimedOut, match="before_source"):
        deadline.check("before_source")


def test_operation_deadline_reports_bounded_remaining_seconds() -> None:
    deadline = OperationDeadline.from_scope(
        {"deadline_at": "2026-07-12T00:00:30+00:00"},
        now=lambda: datetime(2026, 7, 12, 0, 0, 10, tzinfo=UTC),
    )

    assert deadline.remaining_seconds() == 20.0
