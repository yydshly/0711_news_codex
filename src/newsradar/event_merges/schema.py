from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MergeCandidateType(StrEnum):
    LEGACY_IDENTITY = "legacy_identity"
    DETERMINISTIC_MERGE = "deterministic_merge"
    MANUAL_REVIEW = "manual_review"


class MergeCandidateStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    APPLIED = "applied"
    EXPIRED = "expired"
    FAILED = "failed"


class EventMergeFacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: int = Field(gt=0)
    version_number: int = Field(gt=0)
    visibility: str
    canonical_key: str = Field(min_length=1, max_length=255)
    algorithm_versions: tuple[str, ...] = ()
    raw_item_ids: tuple[int, ...]
    source_ids: tuple[str, ...]
    publishers: tuple[str, ...]
    published_at: tuple[datetime, ...]
    safe_url_identities: tuple[str, ...]
    strong_identities: tuple[str, ...]
    object_entities: tuple[str, ...]
    actions: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    key_numbers: tuple[str, ...] = ()


class MergeCandidateDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    left: EventMergeFacts
    right: EventMergeFacts
    candidate_type: MergeCandidateType
    algorithm_version: str = "event-merge-v3"
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_codes: tuple[str, ...]
    zh_reason: str = Field(min_length=1, max_length=1000)
    zh_next_action: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def normalize_pair(self) -> "MergeCandidateDraft":
        if self.left.event_id == self.right.event_id:
            raise ValueError("event_merge_pair_requires_distinct_events")
        if self.left.event_id > self.right.event_id:
            left = self.left
            object.__setattr__(self, "left", self.right)
            object.__setattr__(self, "right", left)
        return self


class MergeCandidateDetail(MergeCandidateDraft):
    id: int = Field(gt=0)
    revision: int = Field(gt=0)
    supersedes_candidate_id: int | None = Field(default=None, gt=0)
    status: MergeCandidateStatus
    generated_operation_id: int = Field(gt=0)
    reviewed_operation_id: int | None = Field(default=None, gt=0)
    applied_operation_id: int | None = Field(default=None, gt=0)
    reviewed_at: datetime | None = None
    result_summary: dict[str, object] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class MergeApplyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    candidate_id: int = Field(gt=0)
    survivor_event_id: int | None = None
    survivor_version_number: int | None = None
    legacy_event_id: int | None = None
    legacy_version_number: int | None = None
    error_code: str | None = None

    @classmethod
    def expired(cls, candidate_id: int, error_code: str) -> "MergeApplyResult":
        return cls(status="expired", candidate_id=candidate_id, error_code=error_code)
