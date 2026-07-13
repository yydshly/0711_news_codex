"""Durable retry policy for terminal operation failures."""

NONRETRYABLE_ERROR_CODES = frozenset(
    {
        "unsupported_action",
        "unsupported_operation_type",
        "unknown_event",
        "unknown_source",
        "invalid_event_scope",
        "operation_timeout",
        "missing_credentials",
        "missing_credential",
        "policy_blocked",
        "invalid_source_remediation_scope",
        "unknown_acquisition_candidate",
        "candidate_requires_credentials",
        "candidate_rejected",
        "original_probe_not_found",
        "candidate_projection_not_found",
        "remediation_probe_failed",
    }
)


def is_retryable_error(error_code: str | None) -> bool:
    return error_code not in NONRETRYABLE_ERROR_CODES
