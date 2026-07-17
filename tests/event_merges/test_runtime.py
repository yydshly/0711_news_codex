from datetime import UTC, datetime, timedelta

import pytest

from newsradar.event_merges.runtime import EventMergeOperationHandler
from newsradar.event_merges.schema import MergeApplyResult
from newsradar.event_merges.service import EventMergeLeaseUnavailable, MergeScanResult
from newsradar.events.quality import QualityInputUnavailable
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus
from newsradar.operations.worker import OperationCancelled

NOW = datetime.now(UTC)


def _scope() -> dict[str, object]:
    return {
        "actor": "test",
        "algorithm_version": "event-merge-v2",
        "algorithm_versions": dict(EVENT_ALGORITHM_VERSIONS),
        "window_end": NOW.isoformat(),
        "idempotency_key": "event-merge-scan:test",
        "deadline_at": (NOW + timedelta(hours=1)).isoformat(),
    }


def _decision_scope(decision: str = "apply") -> dict[str, object]:
    return {
        "candidate_id": 7,
        "decision": decision,
        "actor": "web",
        "idempotency_key": f"event-merge-decision:{decision}:7:test",
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


def test_runtime_propagates_worker_checkpoint_control_flow(monkeypatch) -> None:
    session = type("Session", (), {"close": lambda self: None})()
    cancellation = OperationCancelled("lease-lost")
    monkeypatch.setattr(
        "newsradar.event_merges.runtime.EventMergeService.scan",
        lambda self, operation_id, checkpoint: (_ for _ in ()).throw(cancellation),
    )

    with pytest.raises(OperationCancelled) as caught:
        EventMergeOperationHandler.production(lambda: session)(
            OperationLease(5, 1, 1, "worker", _scope(), "event_merge_scan"),
            lambda _: None,
        )

    assert caught.value is cancellation


def test_runtime_redacts_retryable_session_factory_failure() -> None:
    secret = "postgresql://user:private-password@database/news"

    def fail_session():
        raise RuntimeError(secret)

    result = EventMergeOperationHandler.production(fail_session)(
        OperationLease(5, 1, 1, "worker", _scope(), "event_merge_scan"),
        lambda _: None,
    )

    assert result.status is OperationStatus.FAILED
    assert result.error_code == "event_merge_runtime_unavailable"
    assert result.retryable is True
    assert secret not in (result.error_message or "")


def test_merge_runtime_rejects_bare_event_id_scope_before_opening_session() -> None:
    handler = EventMergeOperationHandler.production(
        lambda: (_ for _ in ()).throw(AssertionError("session must not open"))
    )

    result = handler(
        OperationLease(
            1,
            1,
            1,
            "worker",
            {"event_id": 1, "target_event_id": 2, "actor": "web"},
            "event_merge",
        ),
        lambda _: None,
    )

    assert result.status is OperationStatus.FAILED
    assert result.error_code == "event_merge_candidate_required"
    assert result.retryable is False


@pytest.mark.parametrize("decision", ["apply", "confirm"])
def test_merge_runtime_applies_candidate_decisions(
    monkeypatch: pytest.MonkeyPatch, decision: str
) -> None:
    session = type("Session", (), {"close": lambda self: None})()
    reviewed: list[tuple[int, str, int]] = []
    applied: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "newsradar.event_merges.runtime.EventMergeService.review",
        lambda self, candidate_id, selected, operation_id: reviewed.append(
            (candidate_id, selected, operation_id)
        ),
    )

    def apply(self, candidate_id, operation_id, checkpoint):
        applied.append((candidate_id, operation_id))
        checkpoint("inside_apply")
        return MergeApplyResult(
            status="succeeded",
            candidate_id=candidate_id,
            survivor_event_id=1,
            survivor_version_number=2,
            legacy_event_id=2,
            legacy_version_number=2,
        )

    monkeypatch.setattr(
        "newsradar.event_merges.runtime.EventMergeService.apply", apply
    )

    result = EventMergeOperationHandler.production(lambda: session)(
        OperationLease(5, 51, 1, "worker", _decision_scope(decision), "event_merge"),
        lambda _: None,
    )

    assert result.status is OperationStatus.SUCCEEDED
    assert applied == [(7, 5)]
    assert reviewed == ([(7, "confirm", 5)] if decision == "confirm" else [])
    assert result.result_summary["candidate_id"] == 7


@pytest.mark.parametrize("decision", ["dismiss", "recheck"])
def test_merge_runtime_review_only_decisions_never_apply(
    monkeypatch: pytest.MonkeyPatch, decision: str
) -> None:
    session = type("Session", (), {"close": lambda self: None})()
    record = type(
        "Candidate",
        (),
        {"id": 8, "status": "dismissed" if decision == "dismiss" else "pending"},
    )()
    monkeypatch.setattr(
        "newsradar.event_merges.runtime.EventMergeService.review",
        lambda self, candidate_id, selected, operation_id: record,
    )
    monkeypatch.setattr(
        "newsradar.event_merges.runtime.EventMergeService.apply",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("review-only decision must not apply")
        ),
    )

    result = EventMergeOperationHandler.production(lambda: session)(
        OperationLease(5, 51, 1, "worker", _decision_scope(decision), "event_merge"),
        lambda _: None,
    )

    assert result.status is OperationStatus.SUCCEEDED
    assert result.result_summary == {"candidate_id": 8, "status": record.status}


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (EventMergeLeaseUnavailable(2), "event_merge_lease_unavailable", True),
        (QualityInputUnavailable("missing relevance"), "event_quality_input_unavailable", False),
        (
            ValueError("event_merge_candidate_not_applicable"),
            "event_merge_candidate_not_applicable",
            False,
        ),
        (
            LookupError("event_merge_candidate_not_found"),
            "event_merge_candidate_not_found",
            False,
        ),
        (RuntimeError("publication failed"), "event_merge_apply_failed", True),
    ],
)
def test_merge_runtime_maps_apply_failures(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    code: str,
    retryable: bool,
) -> None:
    session = type("Session", (), {"close": lambda self: None})()
    monkeypatch.setattr(
        "newsradar.event_merges.runtime.EventMergeService.apply",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )

    result = EventMergeOperationHandler.production(lambda: session)(
        OperationLease(5, 51, 1, "worker", _decision_scope(), "event_merge"),
        lambda _: None,
    )

    assert result.status is OperationStatus.FAILED
    assert result.error_code == code
    assert result.retryable is retryable


def test_merge_runtime_maps_expired_revalidation_to_terminal_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = type("Session", (), {"close": lambda self: None})()
    monkeypatch.setattr(
        "newsradar.event_merges.runtime.EventMergeService.apply",
        lambda *args, **kwargs: MergeApplyResult.expired(
            7, "event_merge_version_changed"
        ),
    )

    result = EventMergeOperationHandler.production(lambda: session)(
        OperationLease(5, 51, 1, "worker", _decision_scope(), "event_merge"),
        lambda _: None,
    )

    assert result.status is OperationStatus.FAILED
    assert result.error_code == "event_merge_version_changed"
    assert result.retryable is False


def test_merge_runtime_timeout_never_opens_session() -> None:
    scope = _decision_scope()
    scope["deadline_at"] = (NOW - timedelta(seconds=1)).isoformat()
    handler = EventMergeOperationHandler.production(
        lambda: (_ for _ in ()).throw(AssertionError("session must not open"))
    )

    result = handler(
        OperationLease(5, 51, 1, "worker", scope, "event_merge"),
        lambda _: None,
    )

    assert result.error_code == "operation_timeout"
    assert result.retryable is False


def test_merge_runtime_propagates_candidate_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = type("Session", (), {"close": lambda self: None})()
    cancellation = OperationCancelled("lease-lost")

    def apply(self, candidate_id, operation_id, checkpoint):
        checkpoint("inside_apply")
        raise AssertionError("checkpoint must cancel")

    monkeypatch.setattr(
        "newsradar.event_merges.runtime.EventMergeService.apply", apply
    )

    with pytest.raises(OperationCancelled) as caught:
        EventMergeOperationHandler.production(lambda: session)(
            OperationLease(5, 51, 1, "worker", _decision_scope(), "event_merge"),
            lambda _: (_ for _ in ()).throw(cancellation),
        )

    assert caught.value is cancellation


@pytest.mark.parametrize("decision", ["dismiss", "recheck"])
def test_review_only_decision_checks_cancellation_before_review(
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
) -> None:
    session = type("Session", (), {"close": lambda self: None})()
    cancellation = OperationCancelled("cancelled-before-review")
    monkeypatch.setattr(
        "newsradar.event_merges.runtime.EventMergeService.review",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("review must not run after cancellation")
        ),
    )

    with pytest.raises(OperationCancelled) as caught:
        EventMergeOperationHandler.production(lambda: session)(
            OperationLease(
                5,
                51,
                1,
                "worker",
                _decision_scope(decision),
                "event_merge",
            ),
            lambda _: (_ for _ in ()).throw(cancellation),
        )

    assert caught.value is cancellation


def test_one_candidate_failure_does_not_poison_next_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = [
        type("Session", (), {"close": lambda self: None})(),
        type("Session", (), {"close": lambda self: None})(),
    ]
    attempts = 0

    def apply(self, candidate_id, operation_id, checkpoint):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("isolated publication failure")
        return MergeApplyResult(
            status="succeeded",
            candidate_id=candidate_id,
            survivor_event_id=1,
            survivor_version_number=2,
            legacy_event_id=2,
            legacy_version_number=2,
        )

    monkeypatch.setattr(
        "newsradar.event_merges.runtime.EventMergeService.apply", apply
    )
    handler = EventMergeOperationHandler.production(lambda: sessions.pop(0))

    failed = handler(
        OperationLease(5, 51, 1, "worker", _decision_scope(), "event_merge"),
        lambda _: None,
    )
    succeeded = handler(
        OperationLease(6, 52, 1, "worker", _decision_scope(), "event_merge"),
        lambda _: None,
    )

    assert failed.error_code == "event_merge_apply_failed"
    assert succeeded.status is OperationStatus.SUCCEEDED
