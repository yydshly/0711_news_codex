from enum import StrEnum


class OperationType(StrEnum):
    PROVIDER_SYNC = "provider_sync"
    SOURCE_SYNC = "source_sync"
    PROVIDER_PROBE = "provider_probe"
    SOURCE_PROBE = "source_probe"
    SOURCE_REMEDIATION = "source_remediation"
    FETCH = "fetch"
    EVENT_PIPELINE = "event_pipeline"
    EVENT_RECLUSTER = "event_recluster"
    EVENT_ENRICH = "event_enrich"
    EVENT_MERGE = "event_merge"
    EVENT_SPLIT = "event_split"
    EVENT_EXCLUDE = "event_exclude"


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
