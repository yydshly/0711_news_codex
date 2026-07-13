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


class RemediationEvidence(BaseModel):
    """Latest bounded evidence for one immutable baseline Target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_key: str | None = None
    candidate_kind: str | None = None
    acquisition_outcome: str | None = None
    acquisition_sample_count: int | None = None
    content_outcome: str | None = None
    content_sample_count: int | None = None
    field_completeness: float | None = None
    trial_eligible: bool | None = None
    trial_reason_zh: str | None = None
    fetch_outcome: str | None = None
    fetch_items_received: int | None = None
    fetch_items_inserted: int | None = None
    html_research_status: str = "不涉及（RSS/API 主路径）"
    final_conclusion_zh: str | None = None


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
    evidence: RemediationEvidence | None = None


class RemediationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_at: datetime
    entries: tuple[RemediationEntry, ...]
    before_trial_count: int | None = None
    after_trial_count: int | None = None
