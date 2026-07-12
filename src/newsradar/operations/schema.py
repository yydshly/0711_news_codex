from enum import StrEnum


class OperationType(StrEnum):
    PROVIDER_SYNC = "provider_sync"
    SOURCE_SYNC = "source_sync"
    PROVIDER_PROBE = "provider_probe"
    SOURCE_PROBE = "source_probe"
    FETCH = "fetch"


class OperationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"

    @classmethod
    def terminal(cls) -> set["OperationStatus"]:
        return {
            cls.SUCCEEDED,
            cls.PARTIAL,
            cls.FAILED,
            cls.INTERRUPTED,
            cls.CANCELLED,
        }


class ErrorCategory(StrEnum):
    VALIDATION = "validation"
    ELIGIBILITY = "eligibility"
    AUTHENTICATION = "authentication"
    TRANSPORT = "transport"
    HTTP = "http"
    PARSING = "parsing"
    PERSISTENCE = "persistence"
    CONFLICT = "conflict"
    LIMIT_EXCEEDED = "limit_exceeded"
    INTERNAL = "internal"
