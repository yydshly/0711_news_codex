from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition


class AcquisitionProbeOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


class AcquisitionProbeSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str | None = None
    title: str | None = Field(default=None, max_length=500)
    channel: str | None = Field(default=None, max_length=200)
    canonical_url: str | None = Field(default=None, max_length=1000)
    published_at: datetime | None = None
    summary: str | None = Field(default=None, max_length=2000)
    engagement: dict[str, int] = Field(default_factory=dict)
    language: str | None = Field(default=None, max_length=32)
    transcript_kind: str | None = Field(default=None, max_length=32)
    text_available: bool | None = None
    text: str | None = Field(default=None, max_length=4000)


class AcquisitionProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    candidate_key: str
    outcome: AcquisitionProbeOutcome
    decision: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    samples: list[AcquisitionProbeSample] = Field(default_factory=list, max_length=5)
    metadata: dict[str, str | int | bool | None] = Field(default_factory=dict)
    reason_zh: str
    error_code: str | None = None
    http_status: int | None = None
    final_url: str | None = None
    latency_ms: float | None = None
    latest_published_at: datetime | None = None
    fields_present: list[str] = Field(default_factory=list)
    field_completeness: float | None = None
    schema_fingerprint: str | None = None
    pagination_detected: bool | None = None
    cache_control: str | None = None
    rate_limit_remaining: int | None = None
    blocked_condition: str | None = None


class ResearchProbe(Protocol):
    async def probe(
        self, source: SourceDefinition, candidate: AcquisitionCandidate, limit: int = 5
    ) -> AcquisitionProbeResult: ...


def probe_result(
    source: SourceDefinition,
    candidate: AcquisitionCandidate,
    outcome: AcquisitionProbeOutcome,
    reason_zh: str,
    error_code: str | None = None,
    *,
    samples: list[AcquisitionProbeSample] | None = None,
    metadata: dict[str, str | int | bool | None] | None = None,
    decision: str | None = None,
    **evidence: object,
) -> AcquisitionProbeResult:
    """Build a uniformly bounded, credential-free research result."""
    return AcquisitionProbeResult(
        source_id=source.id,
        candidate_key=candidate.key,
        outcome=outcome,
        decision=decision or candidate.decision.value,
        reason_zh=reason_zh,
        error_code=error_code,
        samples=(samples or [])[:5],
        metadata=metadata or {},
        **evidence,
    )


def public_probe_url(candidate: AcquisitionCandidate) -> str:
    """Evidence URL is the only generic probe target; never accepts embedded auth."""
    url = str(candidate.evidence[0])
    parsed = urlsplit(url)
    if parsed.username or parsed.password:
        raise ValueError("credentialed_url")
    return url
