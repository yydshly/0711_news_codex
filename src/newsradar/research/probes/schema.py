from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Protocol
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition


class AcquisitionProbeOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


class InvalidProbeUrl(ValueError):
    """A probe target violates the public, credential-free request boundary."""


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

    @field_validator("canonical_url")
    @classmethod
    def canonical_url_is_public(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.username or parsed.password:
            raise ValueError("credentialed_url")
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


class AcquisitionProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    candidate_key: str
    outcome: AcquisitionProbeOutcome
    decision: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    samples: list[AcquisitionProbeSample] = Field(default_factory=list, max_length=5)
    metadata: dict[str, object] = Field(default_factory=dict)
    reason_zh: str
    error_code: str | None = None
    http_status: int | None = None
    final_url: str | None = None
    latency_ms: float | None = None
    etag: str | None = None
    last_modified: str | None = None
    sample_count: int = 0
    latest_published_at: datetime | None = None
    fields_present: list[str] = Field(default_factory=list)
    field_completeness: float | None = None
    schema_fingerprint: str | None = None
    pagination_detected: bool | None = None
    cache_control: str | None = None
    rate_limit_remaining: int | None = None
    retry_after_seconds: float | None = None
    earliest_recheck_at: datetime | None = None
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
    bounded_samples = (samples or [])[:5]
    return AcquisitionProbeResult(
        source_id=source.id,
        candidate_key=candidate.key,
        outcome=outcome,
        decision=decision or candidate.decision.value,
        reason_zh=reason_zh,
        error_code=error_code,
        samples=bounded_samples,
        sample_count=len(bounded_samples),
        metadata=sanitize_probe_details(metadata or {}),
        **evidence,
    )


def public_probe_url(candidate: AcquisitionCandidate) -> str:
    """Evidence URL is the only generic probe target; never accepts embedded auth."""
    url = str(candidate.evidence[0])
    parsed = urlsplit(url)
    if parsed.username or parsed.password:
        raise InvalidProbeUrl("credentialed_url")
    if has_sensitive_query(url):
        raise InvalidProbeUrl("sensitive_query")
    return url


def has_sensitive_query(url: str) -> bool:
    """Check decoded query parameter names so percent-encoding cannot bypass the boundary."""
    return any(
        _SENSITIVE_KEY.search(key)
        for key, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True)
    )


def with_http_evidence(
    result: AcquisitionProbeResult, response: httpx.Response, candidate: AcquisitionCandidate
) -> AcquisitionProbeResult:
    url = urlsplit(str(response.url))
    safe_url = urlunsplit((url.scheme, url.netloc, url.path, "", ""))
    fields = [
        field
        for field in candidate.fields
        if any(getattr(sample, field, None) is not None for sample in result.samples)
    ]
    retry_after_seconds = _retry_after_seconds(
        response.headers.get("retry-after"), result.finished_at
    )
    return result.model_copy(
        update={
            "http_status": response.status_code,
            "final_url": safe_url,
            "latency_ms": response.extensions.get("research_latency_ms"),
            "etag": sanitize_response_header_value(response.headers.get("etag")),
            "last_modified": sanitize_response_header_value(response.headers.get("last-modified")),
            "cache_control": sanitize_response_header_value(response.headers.get("cache-control")),
            "rate_limit_remaining": int(response.headers["x-ratelimit-remaining"])
            if response.headers.get("x-ratelimit-remaining", "").isdigit()
            else None,
            "retry_after_seconds": retry_after_seconds,
            "earliest_recheck_at": (
                result.finished_at + timedelta(seconds=retry_after_seconds)
                if retry_after_seconds is not None
                else None
            ),
            "pagination_detected": bool(result.metadata.get("pagination_detected")),
            "fields_present": fields,
            "field_completeness": len(fields) / len(candidate.fields),
            "schema_fingerprint": hashlib.sha256(
                "|".join(sorted(candidate.fields)).encode()
            ).hexdigest()[:32],
            "latest_published_at": max(
                (s.published_at for s in result.samples if s.published_at), default=None
            ),
            "sample_count": len(result.samples),
        }
    )


def _retry_after_seconds(value: str | None, reference: datetime) -> float | None:
    if value is None:
        return None
    stripped = value.strip()
    if stripped.isdigit():
        seconds = int(stripped)
        return float(seconds) if seconds <= _MAX_RETRY_AFTER_SECONDS else None
    try:
        parsed = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    reference = reference if reference.tzinfo is not None else reference.replace(tzinfo=UTC)
    seconds = max(0.0, (parsed - reference).total_seconds())
    return seconds if seconds <= _MAX_RETRY_AFTER_SECONDS else None


_MAX_RETRY_AFTER_SECONDS = 31 * 24 * 60 * 60


_SENSITIVE_KEY = re.compile(
    r"(?i)(authorization|authentication|auth|cookie|api[_-]?key|access[_-]?token|refresh[_-]?token|token|client[_-]?secret|secret|password)"
)
_URL = re.compile(r"https?://[^\s\"'<>]+")
_SENSITIVE_PAIR = re.compile(
    r"(?i)\b(authorization|cookie|api[_-]?key|access[_-]?token|refresh[_-]?token|token|client[_-]?secret|secret|password)\b\s*[:=]\s*[^\s,;&|}]+"
)
_UNSAFE_HEADER_VALUE = re.compile(r"(?i)(?:https?://|\b(?:authorization|cookie|bearer|basic)\b)")


def sanitize_response_header_value(value: str | None) -> str | None:
    """Allow bounded operational header values only when they contain no secret-bearing data."""
    if value is None:
        return None
    value = value.strip()
    if len(value) > 512 or _UNSAFE_HEADER_VALUE.search(value) or _SENSITIVE_PAIR.search(value):
        return None
    return value


def sanitize_probe_details(value: object) -> object:
    """Remove credential-bearing structure and URL query/fragment evidence recursively."""
    if isinstance(value, dict):
        return {
            str(key): sanitize_probe_details(item)
            for key, item in value.items()
            if not _SENSITIVE_KEY.search(str(key))
        }
    if isinstance(value, list):
        return [sanitize_probe_details(item) for item in value]
    if isinstance(value, str):
        return _SENSITIVE_PAIR.sub("[REDACTED]", _URL.sub(_sanitize_url_match, value))
    return value


def _sanitize_url_match(match: re.Match[str]) -> str:
    parsed = urlsplit(match.group(0))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
