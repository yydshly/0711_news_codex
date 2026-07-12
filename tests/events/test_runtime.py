from newsradar.events.runtime import EventOperationHandler
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus


def test_event_handler_rejects_invalid_pipeline_scope() -> None:
    handler = EventOperationHandler(lambda: None)
    result = handler(OperationLease(1, 1, 1, "worker", {}, "event_pipeline"), lambda _: None)

    assert result.status is OperationStatus.FAILED
    assert result.error_code == "invalid_event_scope"
