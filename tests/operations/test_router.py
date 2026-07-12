from newsradar.operations.repository import OperationLease
from newsradar.operations.router import OperationRouter
from newsradar.operations.schema import OperationStatus
from newsradar.operations.worker import OperationResult


def _lease(operation_type: str) -> OperationLease:
    return OperationLease(1, 1, 1, "worker", {}, operation_type)


def test_router_dispatches_fetch_and_event_handlers() -> None:
    def fetch(lease, checkpoint):
        return OperationResult(result_summary={"kind": "fetch"})

    def event(lease, checkpoint):
        return OperationResult(result_summary={"kind": "event"})

    result = OperationRouter({"fetch": fetch, "event_pipeline": event})(
        _lease("event_pipeline"), lambda _: None
    )

    assert result.status is OperationStatus.SUCCEEDED
    assert result.result_summary == {"kind": "event"}


def test_router_rejects_unknown_operation_type_without_retry() -> None:
    result = OperationRouter({})(_lease("unknown"), lambda _: None)

    assert result.status is OperationStatus.FAILED
    assert result.error_code == "unsupported_operation_type"
    assert result.retryable is False
