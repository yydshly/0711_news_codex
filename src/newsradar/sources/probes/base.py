from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from newsradar.credentials import CredentialProvider, SettingsCredentials
from newsradar.sources.schema import AccessMethod, SourceDefinition, SourceStatus


class ProbeOutcome(StrEnum):
    SUCCESS = "success"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    FAILED = "failed"


def classify_sample_quality(
    sample_count: int, field_completeness: float
) -> tuple[ProbeOutcome, SourceStatus, str | None]:
    if sample_count == 0:
        return ProbeOutcome.DEGRADED, SourceStatus.DEGRADED, "no_content"
    if field_completeness < 0.9:
        return ProbeOutcome.DEGRADED, SourceStatus.DEGRADED, "incomplete_fields"
    return ProbeOutcome.SUCCESS, SourceStatus.CANDIDATE, None


class ProbeSample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_id: str | None = None
    title: str | None = None
    canonical_url: str | None = None
    published_at: datetime | None = None
    author: str | None = None
    summary: str | None = None
    content: str | None = None
    engagement: float | None = None
    discussion_url: str | None = None
    raw_keys: list[str] = Field(default_factory=list)

    def fields_present(self) -> set[str]:
        return {
            field
            for field in (
                "title",
                "canonical_url",
                "published_at",
                "author",
                "summary",
                "content",
                "engagement",
                "discussion_url",
            )
            if getattr(self, field) not in (None, "")
        }


class ProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    access_kind: str
    access_url: str
    outcome: ProbeOutcome
    started_at: datetime
    finished_at: datetime
    latency_ms: float | None = None
    http_status: int | None = None
    response_headers: dict[str, str] = Field(default_factory=dict)
    final_url: str | None = None
    cross_domain_redirect: bool = False
    content_type: str | None = None
    content_length: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    cache_control: str | None = None
    rate_limit_remaining: int | None = None
    rate_limit_reset: str | None = None
    pagination_detected: bool = False
    sample_count: int = 0
    duplicate_ratio: float = 0.0
    field_completeness: float = 0.0
    latest_published_at: datetime | None = None
    schema_fingerprint: str | None = None
    samples: list[ProbeSample] = Field(default_factory=list)
    suggested_status: SourceStatus
    reason: str
    error_code: str | None = None


def utcnow() -> datetime:
    return datetime.now(UTC)


def schema_fingerprint(items: list[Any]) -> str | None:
    keys: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            keys.update(str(key) for key in item)
    if not keys:
        return None
    encoded = json.dumps(sorted(keys), separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
            try:
                return datetime.strptime(value, pattern).replace(tzinfo=UTC)
            except ValueError:
                pass
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


class BaseProbe:
    def __init__(
        self, client: httpx.AsyncClient, credentials: CredentialProvider | None = None
    ) -> None:
        self.client = client
        self.credentials = credentials or SettingsCredentials()

    async def probe(self, source: SourceDefinition, method: AccessMethod) -> ProbeResult:
        started = utcnow()
        missing = self._missing_credentials(method)
        if missing:
            return self._result(
                source,
                method,
                started,
                ProbeOutcome.BLOCKED,
                SourceStatus.CANDIDATE,
                f"Required credential {missing} is not configured",
                error_code="missing_credential",
            )
        try:
            request_started = time.perf_counter()
            response = await self._request(method)
            latency_ms = (time.perf_counter() - request_started) * 1000
            response.raise_for_status()
            return await self.parse(source, method, response, started, latency_ms)
        except httpx.TimeoutException:
            return self._result(
                source,
                method,
                started,
                ProbeOutcome.FAILED,
                SourceStatus.DEGRADED,
                "Request timed out",
                error_code="timeout",
            )
        except httpx.ConnectError:
            return self._result(
                source,
                method,
                started,
                ProbeOutcome.FAILED,
                SourceStatus.DEGRADED,
                "Could not connect to source",
                error_code="connection_error",
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            outcome = ProbeOutcome.BLOCKED if status in {401, 403, 429} else ProbeOutcome.FAILED
            return self._result(
                source,
                method,
                started,
                outcome,
                SourceStatus.DEGRADED,
                f"HTTP {status}",
                error_code=f"http_{status}",
                http_status=status,
            )
        except (ValueError, json.JSONDecodeError) as exc:
            return self._result(
                source,
                method,
                started,
                ProbeOutcome.FAILED,
                SourceStatus.DEGRADED,
                str(exc),
                error_code="invalid_payload",
            )

    async def _request(self, method: AccessMethod) -> httpx.Response:
        headers = {"User-Agent": "NewsCodexSourceProbe/0.1 (+local audited registry)"}
        headers.update(method.headers)
        if len(method.auth_envs) == 1:
            headers["Authorization"] = f"Bearer {self.credentials.require(method.auth_envs[0])}"
        request_kwargs: dict[str, Any] = {"headers": headers, "follow_redirects": True}
        if method.params:
            request_kwargs["params"] = method.params
        return await self.client.get(str(method.url), **request_kwargs)

    def _missing_credentials(self, method: AccessMethod) -> str | None:
        for name in method.auth_envs:
            try:
                self.credentials.require(name)
            except (KeyError, ValueError):
                return name
        return None

    async def parse(
        self,
        source: SourceDefinition,
        method: AccessMethod,
        response: httpx.Response,
        started: datetime,
        latency_ms: float,
    ) -> ProbeResult:
        raise NotImplementedError

    def _result(
        self,
        source: SourceDefinition,
        method: AccessMethod,
        started: datetime,
        outcome: ProbeOutcome,
        suggested_status: SourceStatus,
        reason: str,
        **kwargs: Any,
    ) -> ProbeResult:
        return ProbeResult(
            source_id=source.id,
            access_kind=method.kind.value,
            access_url=str(method.url),
            outcome=outcome,
            started_at=started,
            finished_at=utcnow(),
            suggested_status=suggested_status,
            reason=reason,
            **kwargs,
        )

    def response_metadata(self, response: httpx.Response) -> dict[str, Any]:
        remaining = response.headers.get("x-ratelimit-remaining")
        original_host = (
            response.history[0].request.url.host if response.history else response.request.url.host
        )
        return {
            "http_status": response.status_code,
            "response_headers": {
                key: value
                for key, value in response.headers.items()
                if key.lower() not in {"authorization", "cookie", "set-cookie"}
            },
            "final_url": str(response.url),
            "cross_domain_redirect": original_host != response.url.host,
            "content_type": response.headers.get("content-type"),
            "content_length": len(response.content),
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
            "cache_control": response.headers.get("cache-control"),
            "rate_limit_remaining": int(remaining) if remaining and remaining.isdigit() else None,
            "rate_limit_reset": response.headers.get("x-ratelimit-reset")
            or response.headers.get("retry-after"),
        }


class UnsupportedProbe(BaseProbe):
    async def probe(self, source: SourceDefinition, method: AccessMethod) -> ProbeResult:
        started = utcnow()
        return self._result(
            source,
            method,
            started,
            ProbeOutcome.BLOCKED,
            SourceStatus.CANDIDATE,
            f"Access kind {method.kind.value} requires a dedicated audited probe",
            error_code="unsupported_access_kind",
        )


def summarize_samples(
    source: SourceDefinition, samples: list[ProbeSample]
) -> tuple[float, float, datetime | None]:
    expected = {field.value for field in source.expected_fields}
    if not samples or not expected:
        return 0.0, 0.0, None
    completeness = sum(
        len(sample.fields_present() & expected) / len(expected) for sample in samples
    )
    urls = [sample.canonical_url for sample in samples if sample.canonical_url]
    duplicate_ratio = 1 - (len(set(urls)) / len(urls)) if urls else 0.0
    published = [sample.published_at for sample in samples if sample.published_at]
    return completeness / len(samples), duplicate_ratio, max(published) if published else None
