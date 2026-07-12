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
    }
)


def is_retryable_error(error_code: str | None) -> bool:
    return error_code not in NONRETRYABLE_ERROR_CODES
