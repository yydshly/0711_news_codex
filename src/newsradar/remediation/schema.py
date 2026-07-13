from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class FailureCategory(StrEnum):
    NETWORK_TRANSIENT = "network_transient"
    RATE_LIMITED = "rate_limited"
    ENDPOINT_CHANGED = "endpoint_changed"
    CONTENT_INCOMPLETE = "content_incomplete"
    AUTHENTICATION_OR_POLICY = "authentication_or_policy"
    UNKNOWN = "unknown"


class RemediationEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    source_name: str
    original_probe_id: int
    original_finished_at: datetime
    category: FailureCategory
    reason_zh: str
    next_action_zh: str
    access_url: str | None = None


class RemediationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_at: datetime
    entries: tuple[RemediationEntry, ...]
