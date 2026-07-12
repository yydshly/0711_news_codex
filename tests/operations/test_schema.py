from newsradar.operations.schema import ErrorCategory, OperationStatus, OperationType


def test_operation_status_has_terminal_states() -> None:
    assert OperationStatus.terminal() == {
        OperationStatus.SUCCEEDED,
        OperationStatus.PARTIAL,
        OperationStatus.FAILED,
        OperationStatus.INTERRUPTED,
        OperationStatus.CANCELLED,
    }


def test_operation_enums_match_the_runtime_contract() -> None:
    assert {member.value for member in OperationType} == {
        "provider_sync",
        "source_sync",
        "provider_probe",
        "source_probe",
        "fetch",
        "event_pipeline",
        "event_recluster",
        "event_enrich",
        "event_merge",
        "event_split",
        "event_exclude",
    }
    assert {member.value for member in ErrorCategory} == {
        "validation",
        "eligibility",
        "authentication",
        "transport",
        "http",
        "parsing",
        "persistence",
        "conflict",
        "limit_exceeded",
        "internal",
    }
