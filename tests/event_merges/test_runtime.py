from datetime import UTC, datetime, timedelta

from newsradar.event_merges.runtime import EventMergeOperationHandler
from newsradar.event_merges.service import MergeScanResult
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus

NOW = datetime.now(UTC)


def _scope() -> dict[str, object]:
    return {
        "actor": "test",
        "algorithm_version": "event-merge-v1",
        "algorithm_versions": dict(EVENT_ALGORITHM_VERSIONS),
        "window_end": NOW.isoformat(),
        "idempotency_key": "event-merge-scan:test",
        "deadline_at": (NOW + timedelta(hours=1)).isoformat(),
    }


def test_runtime_validates_scope_before_opening_session() -> None:
    handler = EventMergeOperationHandler.production(
        lambda: (_ for _ in ()).throw(AssertionError("session must not open"))
    )

    result = handler(
        OperationLease(1, 1, 1, "worker", {}, "event_merge_scan"), lambda _: None
    )

    assert result.status is OperationStatus.FAILED
    assert result.error_code == "invalid_event_merge_scan_scope"
    assert result.retryable is False


def test_runtime_maps_scan_result_without_network(monkeypatch) -> None:
    session = type("Session", (), {"close": lambda self: None})()
    scan_result = MergeScanResult(
        candidate_type_counts={"manual_review": 1},
        status_counts={"pending": 1},
        current_event_count=2,
        pair_count=1,
    )
    monkeypatch.setattr(
        "newsradar.event_merges.runtime.EventMergeService.scan",
        lambda self, operation_id, checkpoint: scan_result,
    )
    handler = EventMergeOperationHandler.production(lambda: session)

    result = handler(
        OperationLease(5, 1, 1, "worker", _scope(), "event_merge_scan"),
        lambda _: None,
    )

    assert result.status is OperationStatus.SUCCEEDED
    assert result.result_summary == scan_result.as_dict()


def test_runtime_reports_isolated_scan_failures_as_partial(monkeypatch) -> None:
    session = type("Session", (), {"close": lambda self: None})()
    monkeypatch.setattr(
        "newsradar.event_merges.runtime.EventMergeService.scan",
        lambda self, operation_id, checkpoint: MergeScanResult(
            failure_reasons={"fact_load_failed": 1}, current_event_count=2
        ),
    )

    result = EventMergeOperationHandler.production(lambda: session)(
        OperationLease(5, 1, 1, "worker", _scope(), "event_merge_scan"),
        lambda _: None,
    )

    assert result.status is OperationStatus.PARTIAL
    assert result.retryable is False
